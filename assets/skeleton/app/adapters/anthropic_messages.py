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


def _usage_input_output(u: Any, prompt: str, completion: str) -> dict[str, Any]:
    if u.input_tokens or u.output_tokens or u.thinking_tokens:
        usage: dict[str, Any] = {
            "input_tokens": int(u.input_tokens or 0),
            "output_tokens": int(u.output_tokens or 0),
        }
        # Anthropic extended thinking：可选把思维链 token 单独标出
        if u.thinking_tokens:
            usage["thinking_tokens"] = int(u.thinking_tokens)
        return usage
    return {"input_tokens": estimate_tokens(prompt), "output_tokens": estimate_tokens(completion)}


async def _gen_stream(client: Any, prompt: str, tools: list[ToolDef],
                      model: str, model_id: str | None = None) -> AsyncIterator[bytes]:
    """流式：thinking/text 各开一个 content_block，增量走 *_delta，符合 Anthropic SSE 标准。"""
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

    thinking_index: int | None = None
    thinking_open = False
    text_index: int | None = None
    text_open = False

    async def _close_thinking() -> AsyncIterator[bytes]:
        nonlocal thinking_open
        if thinking_open and thinking_index is not None:
            yield _sse("content_block_stop", {"type": "content_block_stop", "index": thinking_index})
            thinking_open = False

    async def _close_text() -> AsyncIterator[bytes]:
        nonlocal text_open
        if text_open and text_index is not None:
            yield _sse("content_block_stop", {"type": "content_block_stop", "index": text_index})
            text_open = False

    async for ir in stream_with_retry(client, prompt, tools, model_id=model_id):
        if ir.kind == "error":
            async for c in _close_thinking():
                yield c
            async for c in _close_text():
                yield c
            yield _sse("error", {"type": "error",
                                 "error": {"type": "api_error", "message": ir.error or "unknown"}})
            return
        if ir.kind == "thinking" and ir.thinking:
            # 若 text 已开再来 thinking，先关 text（少见，保持块边界合法）
            async for c in _close_text():
                yield c
            if not thinking_open:
                thinking_index = index
                index += 1
                thinking_open = True
                yield _sse("content_block_start", {
                    "type": "content_block_start", "index": thinking_index,
                    "content_block": {"type": "thinking", "thinking": "", "signature": ""},
                })
            yield _sse("content_block_delta", {
                "type": "content_block_delta", "index": thinking_index,
                "delta": {"type": "thinking_delta", "thinking": ir.thinking},
            })
        if ir.kind == "text" and ir.text:
            async for c in _close_thinking():
                yield c
            parts.append(ir.text)
            clean = strip_tool_calls(ir.text)
            if clean:
                if not text_open:
                    text_index = index
                    index += 1
                    text_open = True
                    yield _sse("content_block_start", {
                        "type": "content_block_start", "index": text_index,
                        "content_block": {"type": "text", "text": ""},
                    })
                yield _sse("content_block_delta", {
                    "type": "content_block_delta", "index": text_index,
                    "delta": {"type": "text_delta", "text": clean},
                })
            if tools:
                calls = parse_tool_calls(ir.text, known_names={t.name for t in tools})
                if calls:
                    stop_reason = "tool_use"
                    async for c in _close_text():
                        yield c
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

    async for c in _close_thinking():
        yield c
    async for c in _close_text():
        yield c

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
    # thinking 与 tool_use / text 并列，tool 路径不得丢弃 thinking
    if thinking_text:
        content.append({"type": "thinking", "thinking": thinking_text, "signature": ""})
    stop_reason = "end_turn"
    if tools:
        calls = parse_tool_calls(full_text, known_names={t.name for t in tools})
        if calls:
            stop_reason = "tool_use"
            content.extend([
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                for c in calls
            ])
        else:
            content.append({"type": "text", "text": full_text})
    else:
        content.append({"type": "text", "text": full_text})
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
