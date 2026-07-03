"""UpstreamClient 占位：上游请求 + 多模态上传。

实现 :meth:`stream`：构造请求（URL/headers/body，注入 ``self._auth.get_auth()``），发送，
按上游协议解析响应（SSE / JSON Lines / 轮询），用 ``self._parser.parse(raw)`` 产 IREvent。
多模态：:meth:`upload_image` / :meth:`upload_file` 按上游范式实现
（JSON+base64 单步 / 对象存储 presigned 三步）。参考 references/upstream-adapters.md 与 capture-flow.md。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.events import IREvent
from app.upstream.base import UpstreamClient


class DefaultUpstreamClient(UpstreamClient):
    def __init__(self, account, settings, http_client, auth, parser) -> None:
        self._account = account
        self._settings = settings
        self._http = http_client
        self._auth = auth
        self._parser = parser

    async def stream(self, prompt: str, model_id: str | None = None, **kw: Any) -> AsyncIterator[IREvent]:
        raise NotImplementedError(
            "实现目标网站上游请求：构造请求(URL/headers/body, 注入 self._auth.get_auth())，发送，"
            "按协议(SSE/JSON Lines/轮询)解析，用 self._parser.parse(raw) 产 IREvent。"
            "参考 references/upstream-adapters.md 与 capture-flow.md。"
        )
        yield ""  # type: ignore[unreachable]  # pragma: no cover  # 声明本函数为 async generator
