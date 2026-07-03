"""EventParser 占位：上游原生事件 → IREvent（换上游唯一核心改动）。

实现 :meth:`parse`：``raw`` 是上游单个事件（dict/bytes/str，依上游协议），返回 0..n 个
:class:`~app.events.IREvent`。IREvent kind ∈ text/thinking/tool/finish/error；
详见 app/events.py 与 references/architecture.md。
"""
from __future__ import annotations

from typing import Any

from app.events import IREvent
from app.upstream.base import EventParser


class DefaultParser(EventParser):
    def parse(self, raw: Any) -> list[IREvent]:
        raise NotImplementedError(
            "实现目标网站原生事件 → IREvent 的解析（这是换上游唯一必改的核心）。"
            "参考 references/architecture.md 的 IREvent 契约。"
        )
