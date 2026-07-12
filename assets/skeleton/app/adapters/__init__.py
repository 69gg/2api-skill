"""adapter 公共工具：messages 归一化、model 映射（委托 upstream registry）、system 软化。

模型目录来自 :mod:`app.upstream.models`（占位，用 scripts/probe_catalog.py 探测后填入），
本模块不再硬编码 catalog。
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


def flatten_text(content: Any) -> str:
    """OpenAI/Anthropic content（str 或 content block 数组）→ 纯文本，保留 thinking/reasoning block。"""
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
                    out.append(c.get("text", ""))
                elif t in ("thinking", "redacted_thinking"):
                    cot = _thinking_text(c)
                    if cot:
                        out.append(cot)
                elif t == "reasoning":
                    cot = _reasoning_text(c)
                    if cot:
                        out.append(cot)
                elif "text" in c:
                    out.append(str(c["text"]))
            else:
                out.append(str(c))
        return "\n\n".join(out)
    return str(content)


def _assistant_tool_call_jsons(m: dict[str, Any]) -> list[str]:
    """提取 assistant 消息里的工具调用（兼容 OpenAI tool_calls 与 Anthropic tool_use block），
    返回每个调用的 JSON 字符串（{"name":..., "arguments":...}）。

    把历史 tool_call 渲染成围栏送回上游，比丢弃显著提高后续工具调用成功率（强模仿效应）。
    """
    blocks: list[str] = []
    for tc in (m.get("tool_calls") or []):  # OpenAI
        fn = (tc or {}).get("function") or {}
        raw = fn.get("arguments", "{}")
        try:
            args = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (json.JSONDecodeError, ValueError):
            args = {}
        blocks.append(json.dumps({"name": fn.get("name", ""), "arguments": args}, ensure_ascii=False))
    content = m.get("content")
    if isinstance(content, list):  # Anthropic tool_use blocks
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                blocks.append(json.dumps(
                    {"name": c.get("name", ""), "arguments": c.get("input") or {}}, ensure_ascii=False))
    return blocks


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
) -> str:
    """把 messages 拍平成发给上游的单条用户消息（带角色与 system 前缀）。

    逆向场景下上游 thread 通常一次性，故把整段历史压成一条消息。system 经软化包装；
    assistant 历史工具调用渲染成 ``<tool_call>`` 围栏（few-shot）；tool 角色自然化为观测。

    若客户端未传任何非空 system，且提供了 ``model_id``，则前置注入缺省身份提示
    （声明真实 model id、禁止提及平台；见 :func:`default_identity_system`）。有客户端
    system 时不注入、不覆盖。
    """
    parts: list[str] = []
    # 缺省身份：不走 soften_system（本身不是客户端硬 system，无需弱化）
    if model_id and not _has_nonempty_system(messages):
        parts.append(default_identity_system(model_id=model_id))

    for m in messages:
        role = m.get("role", "user")
        reasoning = m.get("reasoning_content")  # OpenAI 风格 CoT
        cot_prefix = f"<reasoning>\n{reasoning}\n</reasoning>\n\n" if isinstance(reasoning, str) and reasoning else ""

        if role == "system":
            content = flatten_text(m.get("content"))
            softened = soften_system(content, lang=_lang_of(content))
            if not softened:
                continue  # 空 / 纯垃圾 system 不写入（避免占位空段）
            parts.append(f"{cot_prefix}{softened}")
        elif role == "assistant":
            body = flatten_text(m.get("content"))
            tc_jsons = _assistant_tool_call_jsons(m)
            if tc_jsons:
                fence = "\n".join(f"<tool_call>{b}</tool_call>" for b in tc_jsons)
                body = f"{body}\n{fence}".strip() if body else fence
            parts.append(f"{cot_prefix}[assistant]\n{body}")
        elif role == "tool":
            content = flatten_text(m.get("content"))
            parts.append(f"{cot_prefix}[tool_result]\n{content}"
                         "\n\n(Observation above. Continue with the next step if the task isn't finished.)")
        else:
            parts.append(f"{cot_prefix}[user]\n{flatten_text(m.get('content'))}")
    return "\n\n".join(parts)
