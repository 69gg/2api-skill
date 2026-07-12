"""EventParser 占位：上游原生事件 → IREvent（换上游唯一核心改动）。

实现 :meth:`parse`：``raw`` 是上游单个事件（dict/bytes/str，依上游协议），返回 0..n 个
:class:`~app.events.IREvent`。IREvent kind ∈ text/thinking/tool/finish/error；
详见 app/events.py 与 references/architecture.md。

**reasoning / thinking 出站（强制）**：
上游若返回思维链，**必须**产出 ``IREvent(kind="thinking", thinking=...)``，
禁止只塞进 ``kind="text"``。常见上游字段名（解析时按实际抓包选用）：

- ``thinking`` / ``thinking_text`` / ``reasoning`` / ``reasoning_content``
- ``delta.reasoning_content``（OpenAI/DeepSeek 风格 SSE）
- ``content_block.thinking`` / ``thinking_delta``（Anthropic 风格）
- ``summary_text`` / ``reasoning_summary``（Responses 风格）

adapter 层会把 thinking 映射为各协议标准字段：

| 协议 | 非流式 | 流式 |
|---|---|---|
| OpenAI Chat | ``message.reasoning_content`` | ``delta.reasoning_content`` |
| OpenAI Responses | ``output[]`` 中 ``type=reasoning`` | ``response.reasoning_*`` 事件 |
| Anthropic Messages | ``content[]`` 中 ``type=thinking`` | ``thinking_delta`` content_block |

若上游 usage 含思维链 token，填入 ``Usage.thinking_tokens``。
"""
from __future__ import annotations

from typing import Any

from app.events import IREvent
from app.upstream.base import EventParser


class DefaultParser(EventParser):
    def parse(self, raw: Any) -> list[IREvent]:
        raise NotImplementedError(
            "实现目标网站原生事件 → IREvent 的解析（这是换上游唯一必改的核心）。"
            "上游若有 reasoning/thinking 字段，必须产出 IREvent(kind='thinking')；"
            "参考 references/architecture.md 的 IREvent 契约与 references/api-endpoints.md。"
        )
