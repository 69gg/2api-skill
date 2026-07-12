"""OpenAI /v1/responses 兼容接口（typed SSE events + tool calls + v1 key 校验）。"""
from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.adapters import extract_user_prompt, normalize_model, upstream_id_for
from app.deps import get_client, verify_api_key
from app.orchestrator import stream_with_retry
from app.tokens import estimate_tokens, first_usage
from app.tools import ToolDef, parse_tool_calls, strip_tool_calls

router = APIRouter()


class ResponsesRequest(BaseModel):
    model: str | None = None
    input: Any = None
    instructions: str | None = None
    stream: bool = False
    tools: list[dict[str, Any]] | None = None
    model_config = {"extra": "ignore"}


def _resp_id() -> str:
    return f"resp_{uuid.uuid4().hex[:24]}"


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def _input_to_messages(inp: Any, instructions: str | None) -> list[dict[str, Any]]:
    """把 Responses 的 input 归一成 chat-style messages（供 extract_user_prompt）。

    支持：
    - str / message 项
    - ``function_call`` → assistant + tool_calls（保留 id/name/arguments 结构）
    - ``function_call_output`` → role=tool + tool_call_id + content
    """
    if isinstance(inp, str):
        msgs: list[dict[str, Any]] = [{"role": "user", "content": inp}]
    elif isinstance(inp, list):
        msgs = []
        for it in inp:
            if not isinstance(it, dict):
                msgs.append({"role": "user", "content": str(it)})
                continue
            itype = it.get("type")
            if itype == "message":
                msgs.append({
                    "role": it.get("role", "user"),
                    "content": it.get("content", it),
                    **({"tool_calls": it["tool_calls"]} if it.get("tool_calls") else {}),
                })
            elif itype == "reasoning":
                summary = it.get("summary") or []
                msgs.append({
                    "role": "assistant",
                    "content": [{"type": "reasoning", "summary": summary}],
                })
            elif itype == "function_call":
                call_id = it.get("call_id") or it.get("id")
                args = it.get("arguments", "{}")
                if not isinstance(args, str):
                    args = json.dumps(args or {}, ensure_ascii=False)
                msgs.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": it.get("name") or "",
                            "arguments": args,
                        },
                    }],
                })
            elif itype == "function_call_output":
                out = it.get("output")
                if out is None:
                    out = it.get("content", "")
                msgs.append({
                    "role": "tool",
                    "tool_call_id": it.get("call_id") or it.get("id"),
                    "content": out if isinstance(out, str) else json.dumps(out, ensure_ascii=False),
                })
            elif it.get("role") == "tool" or itype == "tool":
                msgs.append({
                    "role": "tool",
                    "tool_call_id": it.get("tool_call_id") or it.get("call_id") or it.get("id"),
                    "name": it.get("name"),
                    "content": it.get("content", it.get("output", "")),
                })
            else:
                msgs.append({
                    "role": it.get("role", "user"),
                    "content": it.get("content", it),
                    **({"tool_calls": it["tool_calls"]} if it.get("tool_calls") else {}),
                })
    else:
        msgs = [{"role": "user", "content": str(inp)}]
    if instructions:
        msgs = [{"role": "system", "content": instructions}, *msgs]
    return msgs


def _build_prompt(req: ResponsesRequest, model: str) -> tuple[str, list[ToolDef]]:
    tools = [ToolDef.from_openai(t.get("function", t)) for t in (req.tools or [])]
    msgs = _input_to_messages(req.input, req.instructions)
    base_prompt = extract_user_prompt(msgs, model_id=model)
    return base_prompt, tools


def _usage_obj(u: Any, prompt: str, completion: str) -> dict[str, Any]:
    """Responses usage；含 reasoning 时附 output_tokens_details.reasoning_tokens。"""
    input_tokens = u.input_tokens or estimate_tokens(prompt)
    output_tokens = u.output_tokens or estimate_tokens(completion)
    usage: dict[str, Any] = {"input_tokens": input_tokens, "output_tokens": output_tokens}
    if u.thinking_tokens:
        usage["output_tokens_details"] = {"reasoning_tokens": int(u.thinking_tokens)}
    return usage


async def _collect(client: Any, prompt: str, tools: list[ToolDef],
                   model_id: str | None = None) -> tuple[str, str, list]:
    parts: list[str] = []
    thinking_parts: list[str] = []
    usages: list = []
    async for ir in stream_with_retry(client, prompt, tools, model_id=model_id):
        if ir.kind == "error":
            raise HTTPException(status_code=502, detail=ir.error)
        if ir.kind == "text" and ir.text:
            parts.append(ir.text)
        if ir.kind == "thinking" and ir.thinking:
            thinking_parts.append(ir.thinking)
        if ir.usage_delta:
            usages.append(ir.usage_delta)
        if ir.kind == "finish":
            break
    return "".join(parts), "".join(thinking_parts), usages


async def _gen_stream(client: Any, prompt: str, tools: list[ToolDef],
                      model: str, model_id: str | None = None) -> AsyncIterator[bytes]:
    """流式：thinking 到达即按 Responses 标准帧输出，不攒到末尾。"""
    rid = _resp_id()
    created = int(time.time())

    yield _sse("response.created", {
        "type": "response.created",
        "response": {"id": rid, "object": "response", "created_at": created, "model": model,
                     "status": "in_progress", "output": []},
    })

    parts: list[str] = []
    thinking_parts: list[str] = []
    usages: list = []
    output: list[dict[str, Any]] = []
    rsid: str | None = None
    reasoning_done = False
    text_item_id: str | None = None

    async for ir in stream_with_retry(client, prompt, tools, model_id=model_id):
        if ir.kind == "error":
            yield _sse("error", {"type": "error", "message": ir.error or "unknown"})
            return
        if ir.kind == "thinking" and ir.thinking:
            if rsid is None:
                rsid = f"rs_{uuid.uuid4().hex[:24]}"
                yield _sse("response.reasoning_item.added", {
                    "type": "response.reasoning_item.added",
                    "item": {"type": "reasoning", "id": rsid, "summary": []},
                    "output_index": 0,
                })
            thinking_parts.append(ir.thinking)
            yield _sse("response.reasoning_summary_text.delta", {
                "type": "response.reasoning_summary_text.delta",
                "item_id": rsid, "summary_index": 0, "output_index": 0,
                "delta": ir.thinking,
            })
        if ir.kind == "text" and ir.text:
            # 正文开始前关闭 reasoning 项（标准顺序：reasoning → message）
            if rsid is not None and not reasoning_done:
                thinking_text = "".join(thinking_parts)
                yield _sse("response.reasoning_summary_text.done", {
                    "type": "response.reasoning_summary_text.done",
                    "item_id": rsid, "summary_index": 0, "output_index": 0,
                    "text": thinking_text,
                })
                yield _sse("response.reasoning_item.done", {
                    "type": "response.reasoning_item.done",
                    "output_index": 0,
                    "item": {
                        "type": "reasoning", "id": rsid,
                        "summary": [{"type": "summary_text", "text": thinking_text}],
                    },
                })
                reasoning_done = True
            parts.append(ir.text)
            clean = strip_tool_calls(ir.text)
            if clean:
                if text_item_id is None:
                    text_item_id = f"msg_{uuid.uuid4().hex[:24]}"
                    out_idx = 1 if rsid else 0
                    yield _sse("response.output_item.added", {
                        "type": "response.output_item.added",
                        "output_index": out_idx,
                        "item": {
                            "type": "message", "id": text_item_id,
                            "status": "in_progress", "role": "assistant",
                            "content": [],
                        },
                    })
                yield _sse("response.output_text.delta", {
                    "type": "response.output_text.delta", "delta": clean,
                })
            if tools:
                calls = parse_tool_calls(ir.text, known_names={t.name for t in tools})
                for c in calls:
                    output.append({
                        "type": "function_call", "id": c.id, "call_id": c.id,
                        "name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False),
                        "status": "completed",
                    })
                    output_index = (1 if rsid else 0) + (1 if text_item_id else 0) + len(output) - 1
                    yield _sse("response.output_item.added", {
                        "type": "response.output_item.added", "output_index": output_index,
                        "item": {"type": "function_call", "id": c.id, "call_id": c.id,
                                 "name": c.name, "arguments": "", "status": "in_progress"},
                    })
                    yield _sse("response.function_call_arguments.delta", {
                        "type": "response.function_call_arguments.delta",
                        "output_index": output_index,
                        "delta": json.dumps(c.arguments, ensure_ascii=False),
                    })
                    yield _sse("response.output_item.done", {
                        "type": "response.output_item.done", "output_index": output_index,
                        "item": {"type": "function_call", "id": c.id, "call_id": c.id,
                                 "name": c.name,
                                 "arguments": json.dumps(c.arguments, ensure_ascii=False),
                                 "status": "completed"},
                    })
        if ir.usage_delta:
            usages.append(ir.usage_delta)
        if ir.kind == "finish":
            break

    # 若全程只有 thinking 无 text，收尾时关闭 reasoning
    if rsid is not None and not reasoning_done:
        thinking_text = "".join(thinking_parts)
        yield _sse("response.reasoning_summary_text.done", {
            "type": "response.reasoning_summary_text.done",
            "item_id": rsid, "summary_index": 0, "output_index": 0,
            "text": thinking_text,
        })
        yield _sse("response.reasoning_item.done", {
            "type": "response.reasoning_item.done",
            "output_index": 0,
            "item": {
                "type": "reasoning", "id": rsid,
                "summary": [{"type": "summary_text", "text": thinking_text}],
            },
        })

    full_text = "".join(parts)
    thinking_text = "".join(thinking_parts)
    clean_text = strip_tool_calls(full_text)
    final_output: list[dict[str, Any]] = []
    if thinking_text and rsid:
        final_output.append({
            "type": "reasoning", "id": rsid,
            "summary": [{"type": "summary_text", "text": thinking_text}],
        })
    elif thinking_text:
        final_output.append({
            "type": "reasoning", "id": f"rs_{uuid.uuid4().hex[:24]}",
            "summary": [{"type": "summary_text", "text": thinking_text}],
        })
    final_output.append({
        "type": "message", "id": text_item_id or f"msg_{uuid.uuid4().hex[:24]}",
        "status": "completed", "role": "assistant",
        "content": [{"type": "output_text", "text": clean_text}],
    })
    final_output.extend(output)

    usage = _usage_obj(first_usage(usages), prompt, full_text)
    yield _sse("response.completed", {
        "type": "response.completed",
        "response": {"id": rid, "object": "response", "created_at": created, "model": model,
                     "status": "completed", "output": final_output, "usage": usage},
    })


@router.post("/v1/responses")
async def responses(
    req: ResponsesRequest,
    client: Any = Depends(get_client),
    _: None = Depends(verify_api_key),
) -> Any:
    model = normalize_model(req.model)
    prompt, tools = _build_prompt(req, model)
    model_id = upstream_id_for(model)

    if req.stream:
        return StreamingResponse(_gen_stream(client, prompt, tools, model, model_id),
                                 media_type="text/event-stream")

    full_text, thinking_text, usages = await _collect(client, prompt, tools, model_id)
    clean_text = strip_tool_calls(full_text)
    output: list[dict[str, Any]] = []
    # reasoning 与 function_call / message 并列，tool 路径不得丢弃 thinking
    if thinking_text:
        output.append({
            "type": "reasoning", "id": f"rs_{uuid.uuid4().hex[:24]}",
            "summary": [{"type": "summary_text", "text": thinking_text}],
        })
    tool_items: list[dict[str, Any]] = []
    if tools:
        calls = parse_tool_calls(full_text, known_names={t.name for t in tools})
        if calls:
            tool_items = [{
                "type": "function_call", "id": c.id, "call_id": c.id,
                "name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False),
                "status": "completed",
            } for c in calls]
    if tool_items:
        output.extend(tool_items)
    else:
        output.append({
            "type": "message", "id": f"msg_{uuid.uuid4().hex[:24]}",
            "status": "completed", "role": "assistant",
            "content": [{"type": "output_text", "text": clean_text}],
        })
    return {
        "id": _resp_id(), "object": "response", "created_at": int(time.time()),
        "model": model, "status": "completed", "output": output,
        "usage": _usage_obj(first_usage(usages), prompt, full_text),
    }
