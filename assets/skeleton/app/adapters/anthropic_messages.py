"""Anthropic /v1/messages 兼容接口（流式 + 非流式 + tool_use + usage）+ /v1/messages/count_tokens。"""
from __future__ import annotations

import json
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
from app.tools import ToolDef, new_tool_call_id, parse_tool_calls, strip_tool_calls

router = APIRouter()


class AnthropicMessage(BaseModel):
    role: str
    content: Any = None
    model_config = {"extra": "allow"}


class MessagesRequest(BaseModel):
    model: str | None = None
    messages: list[AnthropicMessage]
    system: Any = None
    stream: bool = False
    tools: list[dict[str, Any]] | None = None
    max_tokens: int | None = None
    thinking: Any = None  # {"type": "enabled", "budget_tokens": int}
    model_config = {"extra": "ignore"}


def _msg_id() -> str:
    return f"msg_{uuid.uuid4().hex[:24]}"


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def _build_prompt(req: MessagesRequest) -> tuple[str, list[ToolDef]]:
    tools = [ToolDef.from_anthropic(t) for t in (req.tools or [])]
    msgs = [m.model_dump() for m in req.messages]
    if req.system is not None:
        sys_text = req.system if isinstance(req.system, str) else json.dumps(req.system, ensure_ascii=False)
        msgs = [{"role": "system", "content": sys_text}, *msgs]
    base_prompt = extract_user_prompt(msgs)
    return base_prompt, tools


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


def _usage_input_output(u: Any, prompt: str, completion: str) -> dict:
    if u.input_tokens or u.output_tokens:
        return {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens}
    return {"input_tokens": estimate_tokens(prompt), "output_tokens": estimate_tokens(completion)}


async def _gen_stream(client: Any, prompt: str, tools: list[ToolDef],
                      model: str, model_id: str | None = None) -> AsyncIterator[bytes]:
    mid = _msg_id()
    yield _sse("message_start", {
        "type": "message_start",
        "message": {"id": mid, "type": "message", "role": "assistant",
                    "model": model, "content": [], "stop_reason": None,
                    "stop_sequence": None, "usage": {"input_tokens": 0, "output_tokens": 0}},
    })

    parts: list[str] = []
    usages: list = []
    index = 0
    stop_reason = "end_turn"
    async for ir in stream_with_retry(client, prompt, tools, model_id=model_id):
        if ir.kind == "error":
            yield _sse("error", {"type": "error",
                                 "error": {"type": "api_error", "message": ir.error or "unknown"}})
            return
        if ir.kind == "thinking" and ir.thinking:
            yield _sse("content_block_start", {
                "type": "content_block_start", "index": index,
                "content_block": {"type": "thinking", "thinking": ir.thinking, "signature": ""},
            })
            yield _sse("content_block_stop", {"type": "content_block_stop", "index": index})
            index += 1
        if ir.kind == "text" and ir.text:
            parts.append(ir.text)
            clean = strip_tool_calls(ir.text)
            if clean:
                yield _sse("content_block_start", {
                    "type": "content_block_start", "index": index,
                    "content_block": {"type": "text", "text": ""},
                })
                yield _sse("content_block_delta", {
                    "type": "content_block_delta", "index": index,
                    "delta": {"type": "text_delta", "text": clean},
                })
                yield _sse("content_block_stop", {"type": "content_block_stop", "index": index})
                index += 1
            if tools:
                calls = parse_tool_calls(ir.text, known_names={t.name for t in tools})
                if calls:
                    stop_reason = "tool_use"
                    for c in calls:
                        yield _sse("content_block_start", {
                            "type": "content_block_start", "index": index,
                            "content_block": {"type": "tool_use", "id": c.id or new_tool_call_id(),
                                              "name": c.name, "input": {}},
                        })
                        yield _sse("content_block_delta", {
                            "type": "content_block_delta", "index": index,
                            "delta": {"type": "input_json_delta",
                                      "partial_json": json.dumps(c.arguments, ensure_ascii=False)},
                        })
                        yield _sse("content_block_stop", {"type": "content_block_stop", "index": index})
                        index += 1
        if ir.usage_delta:
            usages.append(ir.usage_delta)
        if ir.kind == "finish":
            break

    full_text = "".join(parts)
    usage = _usage_input_output(first_usage(usages), prompt, full_text)
    yield _sse("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
        "usage": usage,
    })
    yield _sse("message_stop", {"type": "message_stop"})


@router.post("/v1/messages")
async def messages(
    req: MessagesRequest,
    client: Any = Depends(get_client),
    _: None = Depends(verify_api_key),
) -> Any:
    model = normalize_model(req.model)
    prompt, tools = _build_prompt(req)
    model_id = upstream_id_for(model)

    if req.stream:
        return StreamingResponse(_gen_stream(client, prompt, tools, model, model_id),
                                 media_type="text/event-stream")

    full_text, thinking_text, usages = await _collect(client, prompt, tools, model_id)
    content: list[dict[str, Any]] = []
    if thinking_text:
        content.append({"type": "thinking", "thinking": thinking_text, "signature": ""})
    content.append({"type": "text", "text": full_text})
    stop_reason = "end_turn"
    if tools:
        calls = parse_tool_calls(full_text, known_names={t.name for t in tools})
        if calls:
            stop_reason = "tool_use"
            content = [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                       for c in calls]
    usage = _usage_input_output(first_usage(usages), prompt, full_text)
    return {
        "id": _msg_id(), "type": "message", "role": "assistant", "model": model,
        "content": content, "stop_reason": stop_reason, "stop_sequence": None,
        "usage": usage,
    }


@router.post("/v1/messages/count_tokens")
async def count_tokens(req: MessagesRequest, _: None = Depends(verify_api_key)) -> dict:
    """token 计数（用估算，因为不调用上游）。"""
    prompt, _ = _build_prompt(req)
    return {"input_tokens": estimate_tokens(prompt)}
