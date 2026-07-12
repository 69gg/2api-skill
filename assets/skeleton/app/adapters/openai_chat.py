"""OpenAI /v1/chat/completions 兼容接口（流式 + 非流式 + tool calls + usage + v1 key 校验）。"""
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


class ChatMessage(BaseModel):
    role: str
    content: Any = None
    name: str | None = None
    tool_call_id: str | None = None
    reasoning_content: str | None = None  # DeepSeek / OpenAI o-series 兼容
    model_config = {"extra": "allow"}


class ChatCompletionRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]
    stream: bool = False
    tools: list[dict[str, Any]] | None = None
    model_config = {"extra": "ignore"}


def _completion_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex[:24]}"


def _now() -> int:
    return int(time.time())


def _sse(obj: dict) -> bytes:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode()


def _usage_obj(u: Any, prompt: str, completion: str) -> dict[str, Any]:
    """OpenAI usage：上游真实 usage 优先，否则 token 估算（CJK 感知 + tiktoken 兜底）。

    若有 thinking_tokens，附带 ``completion_tokens_details.reasoning_tokens``
    （o-series / DeepSeek 兼容；reasoning 是 completion 的子集明细，不重复加总）。
    """
    if u.input_tokens or u.output_tokens or u.thinking_tokens:
        prompt_tokens = int(u.input_tokens or 0)
        completion_tokens = int(u.output_tokens or 0)
        usage: dict[str, Any] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
        if u.thinking_tokens:
            usage["completion_tokens_details"] = {"reasoning_tokens": int(u.thinking_tokens)}
        return usage
    p, c = estimate_tokens(prompt), estimate_tokens(completion)
    return {"prompt_tokens": p, "completion_tokens": c, "total_tokens": p + c}


def _build_prompt(req: ChatCompletionRequest, model: str) -> tuple[str, list[ToolDef]]:
    tools = [ToolDef.from_openai(t.get("function", t)) for t in (req.tools or [])]
    base_prompt = extract_user_prompt(
        [m.model_dump() for m in req.messages], model_id=model)
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


async def _gen_stream(client: Any, prompt: str, tools: list[ToolDef],
                      model: str, model_id: str | None = None) -> AsyncIterator[bytes]:
    cid, created = _completion_id(), _now()

    def chunk(delta: dict, finish: str | None = None) -> dict:
        return {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}

    yield _sse(chunk({"role": "assistant"}))
    parts: list[str] = []
    thinking_parts: list[str] = []
    usages: list = []
    saw_tool_calls = False
    async for ir in stream_with_retry(client, prompt, tools, model_id=model_id):
        if ir.kind == "error":
            yield _sse({**chunk({}), "error": {"message": ir.error or "unknown"}})
            return
        if ir.kind == "text" and ir.text:
            parts.append(ir.text)
            if tools:
                calls = parse_tool_calls(ir.text, known_names={t.name for t in tools})
                if calls:
                    saw_tool_calls = True
                    for i, c in enumerate(calls):
                        yield _sse(chunk({"tool_calls": [{
                            "index": i, "id": c.id, "type": "function",
                            "function": {"name": c.name,
                                         "arguments": json.dumps(c.arguments, ensure_ascii=False)},
                        }]}))
            clean = strip_tool_calls(ir.text)
            if clean:
                yield _sse(chunk({"content": clean}))
        if ir.kind == "thinking" and ir.thinking:
            thinking_parts.append(ir.thinking)
            yield _sse(chunk({"reasoning_content": ir.thinking}))
        if ir.usage_delta:
            usages.append(ir.usage_delta)
        if ir.kind == "finish":
            break

    full_text = "".join(parts)
    finish_reason = "tool_calls" if saw_tool_calls else "stop"
    yield _sse(chunk({}, finish=finish_reason) | {
        "usage": _usage_obj(first_usage(usages), prompt, full_text),
    })
    yield b"data: [DONE]\n\n"


@router.post("/v1/chat/completions")
async def chat_completions(
    req: ChatCompletionRequest,
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
    message: dict[str, Any] = {"role": "assistant", "content": full_text}
    if thinking_text:
        message["reasoning_content"] = thinking_text
    finish_reason = "stop"
    if tools:
        calls = parse_tool_calls(full_text, known_names={t.name for t in tools})
        if calls:
            finish_reason = "tool_calls"
            message["content"] = None
            message["tool_calls"] = [{
                "id": c.id, "type": "function",
                "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)},
            } for c in calls]
    return {
        "id": _completion_id(), "object": "chat.completion", "created": _now(), "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": _usage_obj(first_usage(usages), prompt, full_text),
    }
