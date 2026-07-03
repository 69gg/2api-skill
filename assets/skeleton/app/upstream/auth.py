"""AuthProvider 占位：目标网站的认证链。

常见模式（按目标站选其一，参考 references/upstream-adapters.md 与 capture-flow.md）：
- 纯 cookie 回放：``get_auth`` 返回 ``{"Cookie": "..."}``。
- JWT + 刷新：缓存 token，到期前 ``token_refresh_margin`` 秒刷新（参考 promptql2api auth.py）。
- OAuth refresh：用 refresh_token 换 access_token。
"""
from __future__ import annotations

import httpx

from app.upstream.base import AuthProvider


class DefaultAuthProvider(AuthProvider):
    def __init__(self, account, settings, http_client) -> None:
        self._account = account
        self._settings = settings
        self._http: httpx.AsyncClient = http_client

    async def get_auth(self) -> dict[str, str]:
        raise NotImplementedError(
            "实现目标网站的认证注入：返回上游请求所需的头/cookie。"
            "常见：纯 cookie 回放 / JWT+刷新 / OAuth refresh。参考 references/upstream-adapters.md。"
        )

    def is_auth_failure(self, exc: BaseException) -> bool:
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (401, 403):
            return True
        return False
