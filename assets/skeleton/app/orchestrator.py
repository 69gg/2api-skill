"""语义级编排：在 client 与 adapter 之间拼接 tool directive，可选拒绝重试。

有 tools 时 prompt 结构固定为：
  [TOOL PROTOCOL 全文 + tools 列表]  ← 始终最顶端
  [base_prompt: system / history / user]
  [TOOL PROTOCOL REMINDER]           ← 文末再钉一次，抗长历史 recency

拒绝检测（``refusal_detect``）默认关：真流式透传。
开启后：整轮 buffer → 检测拒绝 → 换 retry 变体重试（与 deps 账号换号正交）。
"""
from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from typing import Any

from app.events import IREvent
from app.refusal import is_refusal
from app.tools import (
    ToolDef,
    build_tool_directive,
    build_tool_tail_reminder,
    parse_tool_calls,
)


def _compose_prompt(base_prompt: str, tools: list[ToolDef], *, variant: str = "default") -> str:
    """有 tools：directive 置顶 + base + tail；无 tools：原样。"""
    if not tools:
        return base_prompt
    head = build_tool_directive(tools, variant=variant)
    tail = build_tool_tail_reminder(tools) if variant == "default" else ""
    # retry 变体用整段替换头，仍钉 tail 提醒
    if variant != "default":
        tail = build_tool_tail_reminder(tools)
    return f"{head}\n\n{base_prompt}{tail}"


async def _collect_round(
    client: Any, prompt: str, model_id: str | None,
) -> tuple[list[IREvent], str, bool]:
    """跑一轮 client.stream，收集全部 IREvent 并拼接 text。"""
    events: list[IREvent] = []
    parts: list[str] = []
    had_error = False
    async for ir in client.stream(prompt, model_id=model_id):
        events.append(ir)
        if ir.kind == "error":
            had_error = True
            break
        if ir.kind == "text" and ir.text:
            parts.append(ir.text)
        if ir.kind == "finish":
            break
    return events, "".join(parts), had_error


async def stream_with_retry(
    client: Any,
    base_prompt: str,
    tools: list[ToolDef],
    model_id: str | None = None,
    *,
    max_retries: int | None = None,
) -> AsyncIterator[IREvent]:
    """拼 tool directive 后驱动 client.stream；可选拒绝检测换变体重试。

    - ``base_prompt`` **不含** directive；有 tools 时 head+base+tail。
    - ``refusal_detect=false``（默认）或无 tools：真流式透传。
    - ``refusal_detect=true`` 且有 tools：buffer 一轮；命中拒绝则换 retry 变体重试。
    """
    has_tools = bool(tools)
    if max_retries is None:
        from app.config import get_settings

        settings = get_settings()
        max_retries = settings.tool_call_retries if settings.refusal_detect else 0

    # 默认路径：不 buffer，流式透传
    if not has_tools or max_retries <= 0:
        prompt = _compose_prompt(base_prompt, tools, variant="default")
        async for ir in client.stream(prompt, model_id=model_id):
            yield ir
            if ir.kind in ("error", "finish"):
                return
        return

    # 拒绝检测路径：buffer + 换变体重试
    known = {t.name for t in tools}
    max_attempts = 1 + max_retries
    chosen: list[IREvent] = []
    for attempt in range(max_attempts):
        variant = "retry" if attempt > 0 else "default"
        prompt = _compose_prompt(base_prompt, tools, variant=variant)
        events, full_text, had_error = await _collect_round(client, prompt, model_id)
        if had_error:
            for ev in events:
                yield ev
            return
        chosen = events
        if parse_tool_calls(full_text, known_names=known):
            break
        if not is_refusal(full_text, has_tools=True):
            break
        if attempt + 1 >= max_attempts:
            break
        print(f"[orchestrator] refusal detected (variant={variant}); retry", file=sys.stderr)
    for ev in chosen:
        yield ev
