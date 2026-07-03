"""语义级重试编排：在 client 与 adapter 之间插一层。

整轮 buffer 一轮回复 → 检测 agent 拒绝 → 换 tool 指令变体（default → retry）重建 prompt 重试。
与 :mod:`app.deps`（账号级 503 换号）正交：那层处理认证/额度失效，本层处理 agent 语义级拒绝。

``client`` duck-type：任何带 ``async stream(prompt, model_id=None) -> AsyncIterator[IREvent]``
的对象均可（UpstreamProvider / _RetryingClient）。
"""
from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from typing import Any

from app.events import IREvent
from app.refusal import is_refusal
from app.tools import ToolDef, build_tool_directive, parse_tool_calls


async def _collect_round(
    client: Any, prompt: str, model_id: str | None,
) -> tuple[list[IREvent], str, bool]:
    """跑一轮 client.stream，收集全部 IREvent 并拼接 text。

    返回 ``(events, full_text, had_error)``。``had_error`` 表示本轮含 error 事件（透传不重试）。
    """
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
    """驱动 client.stream，agent 拒绝时换 tool 指令变体重试，yield 最终轮 IREvent 流。

    - ``base_prompt`` **不含** directive；directive 由本函数按变体拼接（重试时 default→retry）。
    - 无 tools 时不判拒绝（纯对话 agent 拒绝可能是合理的），一轮即止。
    - 有 tools 时：产出 tool_call，或非拒绝纯文本 → 即止；命中拒绝 → 换 retry 变体重试，
      最多 ``max_retries`` 次（默认读 ``config.tool_call_retries``）。
    - 底层 error 透传不重试；耗尽仍拒绝 → 输出最后一轮（回退文本）。
    """
    has_tools = bool(tools)
    if max_retries is None:
        from app.config import get_settings

        max_retries = get_settings().tool_call_retries
    max_attempts = 1 + (max_retries if has_tools and max_retries > 0 else 0)
    known = {t.name for t in tools} if has_tools else set()

    chosen: list[IREvent] = []
    for attempt in range(max_attempts):
        variant = "retry" if attempt > 0 else "default"
        directive = build_tool_directive(tools, variant=variant) if has_tools else ""
        prompt = f"{directive}\n\n{base_prompt}" if directive else base_prompt
        events, full_text, had_error = await _collect_round(client, prompt, model_id)
        if had_error:
            for ev in events:
                yield ev
            return
        chosen = events
        if not has_tools:
            break
        if parse_tool_calls(full_text, known_names=known):
            break  # 成功产出 tool_call
        if not is_refusal(full_text, has_tools=True):
            break  # 非拒绝的纯文本（agent 选择不用工具）→ 不重试
        if attempt + 1 >= max_attempts:
            break  # 耗尽，保留这轮回退
        print(f"[orchestrator] refusal detected (variant={variant}); retry", file=sys.stderr)
    for ev in chosen:
        yield ev
