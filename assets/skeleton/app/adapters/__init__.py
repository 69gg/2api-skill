"""adapter 公共工具：messages 归一化、model 映射、system 软化、tool 历史拍扁。

模型目录来自 :mod:`app.upstream.models`（占位，用 scripts/probe_catalog.py 探测后填入），
本模块不再硬编码 catalog。

工具协议双通道：
- **模型输出**：``<tool_call>{...}</tool_call>``（宿主解析）
- **历史进上游**：``[tools]`` + 按 id 并列 call/result（见 :func:`format_tools_history_block`）
"""
from __future__ import annotations

import json
from typing import Any

from app.system_sanitizer import default_identity_system, remove_junk_lines, soften_system
from app.upstream import DefaultModelRegistry

_registry = DefaultModelRegistry()


def supported_models() -> list[dict[str, Any]]:
    """OpenAI 兼容的 /v1/models 列表。"""
    return [{"id": m["id"], "object": "model", "owned_by": m.get("owner", "unknown")}
            for m in _registry.catalog()]


def normalize_model(model: str | None) -> str:
    """客户端传的 model 归一化为 catalog id；空或未知 → 默认。"""
    return _registry.normalize(model)


def upstream_id_for(model_id: str) -> str | None:
    """catalog id → 上游真实模型标识（供 orchestrator/adapter 传给上游）。"""
    return _registry.upstream_id_for(model_id)


def _lang_of(text: str | None) -> str:
    """简单语种检测：含 CJK → zh，否则 en（用于 system 软化包装语）。"""
    if text and any("一" <= c <= "鿿" for c in text):
        return "zh"
    return "en"


def _thinking_text(block: dict[str, Any]) -> str | None:
    """从 Anthropic thinking / redacted_thinking block 提取文本。"""
    if block.get("type") == "thinking":
        t = block.get("thinking")
        if isinstance(t, str) and t:
            return f"<thinking>\n{t}\n</thinking>"
    if block.get("type") == "redacted_thinking":
        return "<redacted_thinking/>"
    return None


def _reasoning_text(block: dict[str, Any]) -> str | None:
    """从 OpenAI Responses reasoning block 提取 summary 文本。"""
    if block.get("type") != "reasoning":
        return None
    summary = block.get("summary") or []
    texts: list[str] = []
    for s in summary:
        if isinstance(s, dict) and s.get("type") == "summary_text":
            texts.append(s.get("text", ""))
    text = "".join(texts)
    return f"<reasoning>\n{text}\n</reasoning>" if text else None


def _coerce_tool_arguments(arguments: dict[str, Any] | Any) -> dict[str, Any]:
    """把 tool arguments 规范为 dict。"""
    if isinstance(arguments, dict):
        return arguments
    if arguments is None:
        return {}
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            return parsed if isinstance(parsed, dict) else {"value": arguments}
        except (json.JSONDecodeError, ValueError):
            return {"value": arguments} if arguments else {}
    return {"value": arguments}


def format_tool_call_fence(
    name: str,
    arguments: dict[str, Any] | Any,
    *,
    call_id: str | None = None,
) -> str:
    """模型**输出**协议：单个 ``<tool_call>{...}</tool_call>``（宿主解析用，可带 id）。"""
    args = _coerce_tool_arguments(arguments)
    payload: dict[str, Any] = {"name": name or "", "arguments": args}
    if call_id:
        payload["id"] = call_id
    return f"<tool_call>{json.dumps(payload, ensure_ascii=False)}</tool_call>"


def format_tools_history_block(entries: list[dict[str, Any]]) -> str:
    """历史上下文中的并行 tool 统一块（调用 + 结果按 id 并列）。

    形态::

        [tools]
        [id1]
        name: Bash
        arguments: {"command": "ls"}
        ---
        result:
        AGENTS.md
        [id2]
        name: Read
        arguments: {"path": "a.py"}
        ---
        result:
        print(1)

    每条 entry：``id`` / ``name`` / ``arguments`` / ``result`` / ``is_error``。
    """
    if not entries:
        return ""
    lines: list[str] = ["[tools]"]
    for e in entries:
        cid = str(e.get("id") or "?").strip() or "?"
        lines.append(f"[{cid}]")
        name = e.get("name")
        if name:
            lines.append(f"name: {name}")
        if "arguments" in e and e.get("arguments") is not None:
            args = _coerce_tool_arguments(e.get("arguments"))
            lines.append(f"arguments: {json.dumps(args, ensure_ascii=False)}")
        if "result" in e and e.get("result") is not None:
            lines.append("---")
            lines.append("result (error):" if e.get("is_error") else "result:")
            body = str(e.get("result") if e.get("result") is not None else "")
            lines.append(body if body else "(empty)")
        lines.append("")
    return "\n".join(lines).rstrip()


def format_tool_role_block(
    content: str,
    *,
    call_id: str | None = None,
    name: str | None = None,
    is_error: bool = False,
) -> str:
    """单条 result 兼容入口 → 统一 ``[tools]`` 块。"""
    return format_tools_history_block([{
        "id": call_id or "?",
        "name": name or "",
        "result": content if content is not None else "",
        "is_error": is_error,
    }])


def _tool_result_body(block: dict[str, Any]) -> str:
    """Anthropic ``tool_result`` block 的 content → 纯文本。"""
    raw = block.get("content")
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        bits: list[str] = []
        for c in raw:
            if isinstance(c, dict):
                t = c.get("type")
                if t in ("text", "input_text", "output_text") or "text" in c:
                    bits.append(str(c.get("text", "")))
            else:
                bits.append(str(c))
        return "\n".join(x for x in bits if x)
    return str(raw)


def flatten_text(content: Any, *, include_tools: bool = False) -> str:
    """OpenAI/Anthropic content → 纯文本。

    默认跳过 tool_use / tool_result（由 :func:`extract_user_prompt` 统一成 ``[tools]``）。
    ``include_tools=True`` 时才内联渲染（少见路径）。
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: list[str] = []
        for c in content:
            if isinstance(c, dict):
                t = c.get("type")
                if t in ("text", "input_text", "output_text"):
                    out.append(c.get("text", "") or "")
                elif t in ("thinking", "redacted_thinking"):
                    cot = _thinking_text(c)
                    if cot:
                        out.append(cot)
                elif t == "reasoning":
                    cot = _reasoning_text(c)
                    if cot:
                        out.append(cot)
                elif t in ("tool_use", "function_call", "tool_result", "function_call_output"):
                    if not include_tools:
                        continue
                    if t == "tool_use":
                        out.append(format_tool_call_fence(
                            str(c.get("name") or ""),
                            c.get("input") or {},
                            call_id=c.get("id") or None,
                        ))
                    elif t == "function_call":
                        out.append(format_tool_call_fence(
                            str(c.get("name") or ""),
                            c.get("arguments") or c.get("input") or {},
                            call_id=c.get("call_id") or c.get("id") or None,
                        ))
                    elif t == "tool_result":
                        out.append(format_tool_role_block(
                            _tool_result_body(c),
                            call_id=c.get("tool_use_id") or c.get("id") or None,
                            name=c.get("name") or None,
                            is_error=bool(c.get("is_error")),
                        ))
                    else:
                        out.append(format_tool_role_block(
                            str(
                                c.get("output")
                                if c.get("output") is not None
                                else c.get("content") or ""
                            ),
                            call_id=c.get("call_id") or c.get("id") or None,
                            name=c.get("name") or None,
                        ))
                elif "text" in c:
                    out.append(str(c["text"]))
            else:
                out.append(str(c))
        return "\n\n".join(x for x in out if x)
    return str(content)


def _extract_call_entries(m: dict[str, Any]) -> list[dict[str, Any]]:
    """从 assistant 消息提取并行 tool 调用 entries（OpenAI tool_calls / content tool_use）。"""
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(call_id: str | None, name: str, arguments: Any) -> None:
        cid = str(call_id or f"call_{len(entries)}").strip() or f"call_{len(entries)}"
        if cid in seen:
            return
        seen.add(cid)
        entries.append({
            "id": cid,
            "name": name or "",
            "arguments": _coerce_tool_arguments(arguments),
        })

    for tc in m.get("tool_calls") or []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        if not isinstance(fn, dict):
            fn = {}
        add(
            tc.get("id") or tc.get("call_id"),
            str(fn.get("name") or tc.get("name") or ""),
            fn.get("arguments", tc.get("arguments", {})),
        )
    content = m.get("content")
    if isinstance(content, list):
        for c in content:
            if not isinstance(c, dict):
                continue
            t = c.get("type")
            if t == "tool_use":
                add(c.get("id"), str(c.get("name") or ""), c.get("input") or {})
            elif t == "function_call":
                add(
                    c.get("call_id") or c.get("id"),
                    str(c.get("name") or ""),
                    c.get("arguments") or c.get("input") or {},
                )
    return entries


def _extract_result_entries_from_message(m: dict[str, Any]) -> list[dict[str, Any]]:
    """从 role=tool/function 或 user(content 含 tool_result) 提取 result entries。"""
    role = (m.get("role") or "").lower()
    entries: list[dict[str, Any]] = []
    if role in ("tool", "function"):
        entries.append({
            "id": str(m.get("tool_call_id") or m.get("id") or "?"),
            "name": str(m.get("name") or ""),
            "result": flatten_text(m.get("content")),
            "is_error": bool(m.get("is_error")),
        })
        return entries
    content = m.get("content")
    if not isinstance(content, list):
        return entries
    for c in content:
        if not isinstance(c, dict):
            continue
        t = c.get("type")
        if t == "tool_result":
            entries.append({
                "id": str(c.get("tool_use_id") or c.get("id") or "?"),
                "name": str(c.get("name") or ""),
                "result": _tool_result_body(c),
                "is_error": bool(c.get("is_error")),
            })
        elif t == "function_call_output":
            entries.append({
                "id": str(c.get("call_id") or c.get("id") or "?"),
                "name": str(c.get("name") or ""),
                "result": str(
                    c.get("output") if c.get("output") is not None else c.get("content") or ""
                ),
                "is_error": bool(c.get("is_error")),
            })
    return entries


def _user_text_without_tools(content: Any) -> str:
    """user content 去掉 tool_result 后的纯文本。"""
    return flatten_text(content, include_tools=False)


def _content_has_tool_payload(content: Any) -> bool:
    """content 是否含 tool_result / function_call_output。"""
    if not isinstance(content, list):
        return False
    return any(
        isinstance(c, dict) and c.get("type") in ("tool_result", "function_call_output")
        for c in content
    )


def _merge_call_and_result_entries(
    calls: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """按 id 把 result 并入 call；无匹配 call 的 result 单独追加。"""
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for c in calls:
        cid = str(c.get("id") or "?")
        if cid not in by_id:
            order.append(cid)
            by_id[cid] = dict(c)
        else:
            by_id[cid].update({k: v for k, v in c.items() if v not in (None, "")})
    for r in results:
        cid = str(r.get("id") or "?")
        if cid not in by_id:
            order.append(cid)
            by_id[cid] = {"id": cid}
        if r.get("name") and not by_id[cid].get("name"):
            by_id[cid]["name"] = r["name"]
        by_id[cid]["result"] = r.get("result") if r.get("result") is not None else ""
        if r.get("is_error"):
            by_id[cid]["is_error"] = True
    return [by_id[cid] for cid in order]


def _has_nonempty_system(messages: list[dict[str, Any]]) -> bool:
    """是否存在非空 system 消息（空白 / 纯垃圾元数据行不算）。"""
    for m in messages:
        if m.get("role") != "system":
            continue
        content = remove_junk_lines(flatten_text(m.get("content")))
        if content:
            return True
    return False


def extract_user_prompt(
    messages: list[dict[str, Any]],
    *,
    model_id: str | None = None,
    soften: bool | None = None,
) -> str:
    """把 messages 拍平成发给上游的单条用户消息（带角色前缀）。

    角色标记：
    - ``[system]`` / ``[user]`` / ``[assistant]``
    - ``[tools]``：并行 tool 调用与结果统一块，按 id 分组（OpenAI / Anthropic / Responses 归一）

    相邻 assistant call 与后续 tool / tool_result 会按 id 合并；call 与 result **都显示**。
    模型**输出**仍用 ``<tool_call>...</tool_call>``。
    tool 协议指令由 orchestrator 始终拼在本函数返回值**之前与之后**。

    system 仅在 ``soften=True``（或配置 ``soften_system=true``）时软化；默认原样 ``[system]\\n...``。
    """
    if soften is None:
        from app.config import get_settings

        soften = bool(get_settings().soften_system)

    parts: list[str] = []
    if model_id and not _has_nonempty_system(messages):
        parts.append(default_identity_system(model_id=model_id))

    i = 0
    n = len(messages)
    while i < n:
        m = messages[i]
        role = (m.get("role") or "user").lower()
        reasoning = m.get("reasoning_content")
        cot_prefix = (
            f"<reasoning>\n{reasoning}\n</reasoning>\n\n"
            if isinstance(reasoning, str) and reasoning else ""
        )

        if role == "system":
            content = flatten_text(m.get("content"))
            if soften:
                body = soften_system(content, lang=_lang_of(content))
            else:
                body = remove_junk_lines(content) if content else ""
                body = body.strip() if body else content.strip()
            if body:
                # 软化时已是柔和框架，不再包 [system]；默认强制 [system] 标签
                if soften:
                    parts.append(f"{cot_prefix}{body}")
                else:
                    parts.append(f"{cot_prefix}[system]\n{body}")
            i += 1
            continue

        if role == "assistant":
            calls = _extract_call_entries(m)
            text_body = flatten_text(m.get("content"), include_tools=False)
            if calls:
                results: list[dict[str, Any]] = []
                j = i + 1
                trailing_user_text = ""
                while j < n:
                    mj = messages[j]
                    rj = (mj.get("role") or "").lower()
                    if rj == "assistant":
                        more = _extract_call_entries(mj)
                        more_text = flatten_text(mj.get("content"), include_tools=False)
                        if more and not (more_text or "").strip():
                            calls.extend(more)
                            j += 1
                            continue
                        break
                    if rj in ("tool", "function"):
                        results.extend(_extract_result_entries_from_message(mj))
                        j += 1
                        continue
                    if rj == "user" and _content_has_tool_payload(mj.get("content")):
                        results.extend(_extract_result_entries_from_message(mj))
                        trailing_user_text = _user_text_without_tools(mj.get("content"))
                        j += 1
                        break
                    break
                entries = _merge_call_and_result_entries(calls, results)
                if text_body:
                    parts.append(f"{cot_prefix}[assistant]\n{text_body}")
                elif cot_prefix:
                    parts.append(cot_prefix.rstrip())
                parts.append(format_tools_history_block(entries))
                if trailing_user_text:
                    parts.append(f"[user]\n{trailing_user_text}")
                i = j
                continue
            parts.append(f"{cot_prefix}[assistant]\n{text_body}")
            i += 1
            continue

        if role in ("tool", "function"):
            results = _extract_result_entries_from_message(m)
            j = i + 1
            while j < n and (messages[j].get("role") or "").lower() in ("tool", "function"):
                results.extend(_extract_result_entries_from_message(messages[j]))
                j += 1
            block = format_tools_history_block(
                _merge_call_and_result_entries([], results)
            )
            if block:
                parts.append(f"{cot_prefix}{block}" if cot_prefix else block)
            i = j
            continue

        if role == "user" and _content_has_tool_payload(m.get("content")):
            results = _extract_result_entries_from_message(m)
            user_text = _user_text_without_tools(m.get("content"))
            block = format_tools_history_block(
                _merge_call_and_result_entries([], results)
            )
            if block:
                parts.append(f"{cot_prefix}{block}" if cot_prefix else block)
            if user_text:
                parts.append(f"[user]\n{user_text}")
            i += 1
            continue

        parts.append(f"{cot_prefix}[user]\n{flatten_text(m.get('content'))}")
        i += 1

    return "\n\n".join(p for p in parts if p)
