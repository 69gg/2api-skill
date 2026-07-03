"""上游适配器入口（换目标网站时只改本目录）。

:func:`get_provider` 组合 Auth + Client + Parser，返回 :class:`UpstreamProvider`。
默认实现（``Default*``）是占位：``stream`` 会抛 ``NotImplementedError`` 提示你实现
auth/client/parser；实现后即可工作。详见 references/upstream-adapters.md。
"""
from __future__ import annotations

from typing import Any

from app.account import Account
from app.config import Settings
from app.upstream.auth import DefaultAuthProvider
from app.upstream.client import DefaultUpstreamClient
from app.upstream.models import MODEL_CATALOG, DefaultModelRegistry
from app.upstream.parser import DefaultParser
from app.upstream.provider import UpstreamProvider

__all__ = ["get_provider", "UpstreamProvider", "MODEL_CATALOG", "DefaultModelRegistry"]


def get_provider(account: Account, settings: Settings, http_client: Any) -> UpstreamProvider:
    """为指定账号构造 UpstreamProvider（组合 Auth + Client + Parser）。"""
    auth = DefaultAuthProvider(account, settings, http_client)
    parser = DefaultParser()
    client = DefaultUpstreamClient(account, settings, http_client, auth, parser)
    return UpstreamProvider(account, settings, http_client, auth, client)
