"""共享 FastAPI 依赖：注入 UpstreamProvider + API key 校验 + 错误分类换号。

每次请求 round-robin 取一个账号的 provider，用 :class:`_RetryingClient` 包一层：
按 :class:`~app.account.FailReason` 分类失效 → ``mark_failed`` → 抛 503，下一次请求自动换号。
v1 的 ``gateway_api_key`` 留空则不校验（无认证）；详见 references/auth-and-errors.md。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.account import Account, AccountPool, FailReason
from app.events import IREvent

_bearer = HTTPBearer(auto_error=False)

# 默认的失效 body 关键词（按目标站定制，见 references/auth-and-errors.md）。
_AUTH_HINTS = ("unauthorized", "invalid token", "not authenticated", "login required")
_BAN_HINTS = ("banned", "suspended", "disabled", "forbidden", "封禁", "封号")
_QUOTA_HINTS = ("quota", "limit reached", "insufficient", "credit", "额度", "配额", "余额不足")
_CF_HINTS = ("cloudflare", "captcha", "turnstile", "challenge", "验证码")


def classify_failure(exc: BaseException) -> FailReason | None:
    """把上游异常映射成 FailReason（默认按 HTTP 状态码 + body 关键词；按目标站定制）。

    返回 None 表示非账号级失效（不换号，原样抛出）。
    """
    status: int | None = None
    body = ""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        try:
            body = exc.response.text.lower()
        except Exception:  # noqa: BLE001
            body = ""
    text = f"{body} {str(exc).lower()}"
    if status in (401, 403) or any(h in text for h in _AUTH_HINTS):
        return FailReason.AUTH_FAILED
    if status == 429 or any(h in text for h in _QUOTA_HINTS):
        return FailReason.QUOTA_EXHAUSTED
    if status == 451 or any(h in text for h in _CF_HINTS):
        return FailReason.CF_CHALLENGE
    if any(h in text for h in _BAN_HINTS):
        return FailReason.BANNED
    return None


class _RetryingClient:
    """duck-type UpstreamProvider：包装 stream，失效时按 FailReason 标记账号并抛 503。

    流式已 yield 部分内容后重试会重复输出，故不自动重试同请求；抛 503 让客户端重试即换号。
    """

    def __init__(self, pool: AccountPool, account: Account, underlying: Any) -> None:
        self._pool = pool
        self._account = account
        self._underlying = underlying

    async def stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[IREvent]:
        try:
            async for ir in self._underlying.stream(*args, **kwargs):
                yield ir
        except Exception as e:  # noqa: BLE001
            reason = classify_failure(e)
            if reason is not None:
                self._pool.mark_failed(self._account, reason)
                raise HTTPException(
                    status_code=503,
                    detail=f"account failed ({reason.value}); retry request to switch account",
                ) from e
            raise


def get_client(request: Request) -> _RetryingClient:
    """round-robin 取一个账号，返回其 _RetryingClient 包装。"""
    st = request.app.state
    pool: AccountPool = st.pool
    providers: dict[str, Any] = st.providers
    acc = pool.next()
    return _RetryingClient(pool, acc, providers[acc.name])


def verify_api_key(
    request: Request,
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """v1 gateway key 校验；未配置 key 则放行（无认证）。每个 /v1 router 都应 Depends 本函数。"""
    settings = request.app.state.settings
    if not settings.gateway_api_key:
        return
    if cred is None or cred.credentials != settings.gateway_api_key:
        raise HTTPException(status_code=401, detail="invalid api key")
