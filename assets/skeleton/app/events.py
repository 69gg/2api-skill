"""统一中间表示（IR）—— 2api 框架的核心数据契约。

上游适配器（``app/upstream/parser.py``）把目标网站的任意原生事件归一成 :class:`IREvent`，
三家 API adapter（``app/adapters/*``）各自消费同一份 IREvent 流，转成 OpenAI / Anthropic 格式。

换上游时**唯一必改**的是 parser（原生事件 → IREvent）；IREvent 本身是稳定契约，勿轻改。
新增需求优先扩 :attr:`ToolEvent.detail`，而非加 IREvent 字段。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

IRKind = Literal["text", "thinking", "tool", "finish", "error"]


@dataclass
class ToolEvent:
    """工具调用 / 工具事件：agent 内置工具的展示，或 prompt 模式解析出的调用。"""

    name: str
    title: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class Usage:
    """token 用量。优先用上游真实值（parser 填 ``usage_delta``）；无则由 :mod:`app.tokens` 估算。"""

    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cached_tokens: int = 0
    cache_creation_tokens: int = 0
    model: str | None = None
    provider: str | None = None

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.thinking_tokens += other.thinking_tokens
        self.cached_tokens += other.cached_tokens
        self.cache_creation_tokens += other.cache_creation_tokens


@dataclass
class IREvent:
    """归一后的单个中间事件。adapter 把它转成各家流式格式。"""

    kind: IRKind
    text: str = ""
    thinking: str = ""
    tool: ToolEvent | None = None
    usage_delta: Usage | None = None
    finish_reason: str | None = None  # "stop" / "length" / "tool_use" / ...
    error: str | None = None
