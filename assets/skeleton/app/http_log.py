"""HTTP 请求/响应访问日志：脱敏 header/body + 耗时 + usage 提取。

中间件记录客户端 → 网关 的 headers/body，以及 网关 → 客户端 的 status/body、
elapsed_ms、从响应中解析的 token usage（若有）。敏感字段脱敏，body 截断。
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# 敏感 header 名（小写）
_SENSITIVE_HEADERS = frozenset({
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-auth-key",
    "proxy-authorization",
    "x-xsrf-token",
    "x-csrf-token",
})

# body 里常见敏感字段
_SENSITIVE_BODY_KEYS = frozenset({
    "password", "password_confirmation", "token", "access_token",
    "refresh_token", "api_key", "authorization", "cookie", "secret",
    "client_secret",
})

_DEFAULT_MAX_BODY = 4000
_MAX_HEADER_VAL = 200
_SSE_DATA_RE = re.compile(r"^data:\s*(.+)$", re.MULTILINE)


def _max_body(settings: Any | None) -> int:
    if settings is None:
        return _DEFAULT_MAX_BODY
    return int(getattr(settings, "log_max_body_chars", None) or _DEFAULT_MAX_BODY)


def redact_headers(headers: Any) -> dict[str, str]:
    """复制 headers 并脱敏敏感值。"""
    out: dict[str, str] = {}
    try:
        items = headers.items()
    except Exception:  # noqa: BLE001
        return out
    for k, v in items:
        key = str(k)
        val = str(v)
        if key.lower() in _SENSITIVE_HEADERS:
            out[key] = _mask(val)
        else:
            out[key] = val if len(val) <= _MAX_HEADER_VAL else val[: _MAX_HEADER_VAL - 1] + "…"
    return out


def _mask(val: str) -> str:
    if not val:
        return ""
    if val.lower().startswith("bearer ") and len(val) > 14:
        return f"Bearer {val[7:11]}…{val[-4:]}"
    if len(val) <= 8:
        return "***"
    return f"{val[:4]}…{val[-4:]}(len={len(val)})"


def redact_body_obj(obj: Any) -> Any:
    """递归脱敏 dict 中的敏感键；字符串过长截断。"""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if str(k).lower() in _SENSITIVE_BODY_KEYS:
                out[k] = _mask(str(v)) if v is not None else v
            else:
                out[k] = redact_body_obj(v)
        return out
    if isinstance(obj, list):
        if len(obj) > 20:
            head = [redact_body_obj(x) for x in obj[:10]]
            tail = [redact_body_obj(x) for x in obj[-5:]]
            return head + [f"…({len(obj) - 15} more items)…"] + tail
        return [redact_body_obj(x) for x in obj]
    if isinstance(obj, str):
        if obj.startswith("data:") and len(obj) > 80:
            return obj[:40] + f"…(data_url len={len(obj)})"
        if len(obj) > 500:
            return obj[:500] + f"…(len={len(obj)})"
        return obj
    return obj


def format_body_for_log(
    raw: bytes | str | None,
    *,
    content_type: str = "",
    max_chars: int = _DEFAULT_MAX_BODY,
) -> str:
    """把 body 转成可打日志的短字符串（JSON 美化 + 脱敏 + 截断）。"""
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        if not raw:
            return ""
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return f"<binary {len(raw)} bytes>"
    else:
        text = raw
    ct = (content_type or "").lower()
    if "json" in ct or text.lstrip().startswith(("{", "[")):
        try:
            obj = json.loads(text)
            redacted = redact_body_obj(obj)
            s = json.dumps(redacted, ensure_ascii=False, indent=2)
            if len(s) > max_chars:
                return s[:max_chars] + f"…(truncated, total_chars={len(s)})"
            return s
        except json.JSONDecodeError:
            pass
    # SSE：逐条 data 行尝试 JSON 脱敏后拼接（仍截断总长）
    if "text/event-stream" in ct or text.lstrip().startswith("data:"):
        parts: list[str] = []
        for m in _SSE_DATA_RE.finditer(text):
            payload = m.group(1).strip()
            if payload == "[DONE]":
                parts.append("data: [DONE]")
                continue
            try:
                obj = json.loads(payload)
                parts.append(
                    "data: " + json.dumps(redact_body_obj(obj), ensure_ascii=False)
                )
            except json.JSONDecodeError:
                if len(payload) > 200:
                    parts.append(f"data: {payload[:200]}…(len={len(payload)})")
                else:
                    parts.append(f"data: {payload}")
        s = "\n".join(parts) if parts else text
        if len(s) > max_chars:
            return s[:max_chars] + f"…(truncated, total_chars={len(s)})"
        return s
    if len(text) > max_chars:
        return text[:max_chars] + f"…(truncated, total_chars={len(text)})"
    return text


def format_headers_for_log(headers: Any) -> str:
    return json.dumps(redact_headers(headers), ensure_ascii=False)


def extract_usage_from_body(raw: bytes | str | None, *, content_type: str = "") -> dict[str, Any] | None:
    """从 OpenAI/Anthropic JSON 或 SSE 响应中尽量提取 usage 对象。"""
    if raw is None:
        return None
    if isinstance(raw, bytes):
        if not raw:
            return None
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    else:
        text = raw
    if not text.strip():
        return None

    def _from_obj(obj: Any) -> dict[str, Any] | None:
        if not isinstance(obj, dict):
            return None
        usage = obj.get("usage")
        if isinstance(usage, dict) and usage:
            return usage
        # Anthropic message 顶层即 usage
        if any(k in obj for k in ("input_tokens", "output_tokens", "prompt_tokens")):
            keys = (
                "input_tokens", "output_tokens", "prompt_tokens", "completion_tokens",
                "total_tokens", "thinking_tokens", "cache_creation_input_tokens",
                "cache_read_input_tokens",
            )
            found = {k: obj[k] for k in keys if k in obj}
            return found or None
        return None

    ct = (content_type or "").lower()
    if "json" in ct or text.lstrip().startswith(("{", "[")):
        try:
            return _from_obj(json.loads(text))
        except json.JSONDecodeError:
            pass

    # SSE：从后往前找带 usage 的 data 帧
    last_usage: dict[str, Any] | None = None
    for m in _SSE_DATA_RE.finditer(text):
        payload = m.group(1).strip()
        if payload == "[DONE]":
            continue
        try:
            u = _from_obj(json.loads(payload))
            if u:
                last_usage = u
        except json.JSONDecodeError:
            continue
    return last_usage


def _settings_from_request(request: Request) -> Any | None:
    return getattr(request.app.state, "settings", None)


class RequestResponseLogMiddleware(BaseHTTPMiddleware):
    """记录请求 header/body、响应 body、耗时、usage；跳过 ``/healthz``。"""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if request.url.path in ("/healthz", "/favicon.ico"):
            return await call_next(request)

        settings = _settings_from_request(request)
        max_chars = _max_body(settings)
        log_req_body = True if settings is None else bool(
            getattr(settings, "log_request_body", True)
        )
        log_resp_body = True if settings is None else bool(
            getattr(settings, "log_response_body", True)
        )

        req_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:10]
        request.state.req_id = req_id
        t0 = time.perf_counter()

        body_bytes = await request.body()

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": body_bytes, "more_body": False}

        request = Request(request.scope, receive)

        client = request.client.host if request.client else "?"
        logger.info(
            "[%s] >>> %s %s client=%s",
            req_id, request.method, request.url.path, client,
        )
        logger.info(
            "[%s] >>> request headers: %s",
            req_id, format_headers_for_log(request.headers),
        )
        if log_req_body:
            if body_bytes:
                logger.info(
                    "[%s] >>> request body (%d bytes):\n%s",
                    req_id, len(body_bytes),
                    format_body_for_log(
                        body_bytes,
                        content_type=request.headers.get("content-type", ""),
                        max_chars=max_chars,
                    ),
                )
            else:
                logger.info("[%s] >>> request body: (empty)", req_id)

        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "[%s] !!! unhandled error elapsed_ms=%.1f",
                req_id, (time.perf_counter() - t0) * 1000,
            )
            raise

        # 聚合响应 body（流式也会缓冲，便于记 usage 与脱敏 body）
        resp_chunks: list[bytes] = []
        body_iter = response.body_iterator
        try:
            async for chunk in body_iter:
                if isinstance(chunk, str):
                    resp_chunks.append(chunk.encode("utf-8"))
                else:
                    resp_chunks.append(chunk)
        finally:
            # Starlette 可能提供 aclose
            aclose = getattr(body_iter, "aclose", None)
            if callable(aclose):
                await aclose()

        resp_body = b"".join(resp_chunks)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        media_type = response.media_type or response.headers.get("content-type", "")
        usage = extract_usage_from_body(resp_body, content_type=media_type)

        logger.info(
            "[%s] <<< response status=%s elapsed_ms=%.1f body_bytes=%d usage=%s",
            req_id,
            response.status_code,
            elapsed_ms,
            len(resp_body),
            json.dumps(usage, ensure_ascii=False) if usage else "null",
        )
        logger.info(
            "[%s] <<< response headers: %s",
            req_id, format_headers_for_log(response.headers),
        )
        if log_resp_body:
            if resp_body:
                logger.info(
                    "[%s] <<< response body (%d bytes):\n%s",
                    req_id, len(resp_body),
                    format_body_for_log(
                        resp_body, content_type=media_type, max_chars=max_chars,
                    ),
                )
            else:
                logger.info("[%s] <<< response body: (empty)", req_id)

        headers = dict(response.headers)
        headers.pop("content-length", None)
        headers["x-request-id"] = req_id
        return Response(
            content=resp_body,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
            background=response.background,
        )


def strip_auth_from_headers_dict(headers: dict[str, str]) -> dict[str, str]:
    """上游请求用：拷贝并脱敏。"""
    return redact_headers(headers)
