"""UpstreamProvider：组合 Auth + Client，对外暴露 duck-type stream() 供电 deps/adapters 用。

duck-type 接口：``async stream(prompt, model_id=None) -> AsyncIterator[IREvent]``。
app.deps._RetryingClient 与 app.orchestrator 均按此接口使用（不依赖具体上游）。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.events import IREvent


class UpstreamProvider:
    def __init__(self, account: Any, settings: Any, http_client: Any, auth: Any, client: Any) -> None:
        self.account = account
        self.settings = settings
        self.http_client = http_client
        self._auth = auth
        self._client = client

    async def stream(self, prompt: str, model_id: str | None = None, **kw: Any) -> AsyncIterator[IREvent]:
        async for ir in self._client.stream(prompt, model_id=model_id, **kw):
            yield ir

    async def upload_image(self, data: bytes, mime: str, filename: str = "") -> str:
        return await self._client.upload_image(data, mime, filename)

    async def upload_file(self, data: bytes, mime: str, filename: str = "") -> str:
        return await self._client.upload_file(data, mime, filename)
