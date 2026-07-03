"""token 计数：优先用上游真实 usage；无则 CJK 感知估算，tiktoken 兜底。

诚实原则：上游无真实 usage 时返回估算值并标注，绝不编造精确值。
CJK 公式 ``cjk*1.3 + ascii/3.5`` 对中英混排比纯 tiktoken cl100k 更准（参考 gpt2api）。
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.events import Usage

# 模型名前缀 → tiktoken encoding 名（claude 系无对应 encoding，统一用 cl100k_base 近似）
_MODEL_ENCODING: dict[str, str] = {
    "gpt-4": "cl100k_base",
    "gpt-3.5": "cl100k_base",
    "claude": "cl100k_base",
}


def estimate_tokens_cjk(text: str) -> int:
    """CJK 感知估算：中文 1.3 token/字，ASCII /3.5，其余按 1.0；至少 1。"""
    if not text:
        return 0
    cjk = sum(1 for c in text if "一" <= c <= "鿿" or "㐀" <= c <= "䶿")
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    other = len(text) - cjk - ascii_chars
    return max(1, int(cjk * 1.3 + ascii_chars / 3.5 + other * 1.0))


@lru_cache(maxsize=8)
def _get_encoding(name: str):  # type: ignore[no-untyped-def]
    try:
        import tiktoken

        return tiktoken.get_encoding(name)
    except Exception:  # noqa: BLE001
        return None


def estimate_tokens(text: str, model: str | None = None) -> int:
    """tiktoken 估算（近似）；tiktoken 不可用或编码失败 → 回退 CJK 估算。"""
    if not text:
        return 0
    enc_name = "cl100k_base"
    if model:
        for k, v in _MODEL_ENCODING.items():
            if model.startswith(k):
                enc_name = v
                break
    enc = _get_encoding(enc_name)
    if enc is None:
        return estimate_tokens_cjk(text)
    try:
        return len(enc.encode(text))
    except Exception:  # noqa: BLE001
        return estimate_tokens_cjk(text)


def first_usage(parts: list[Usage | None]) -> Usage:
    """取第一个非零 usage。

    agent 一次问答可能跑多轮（每轮重读全上下文，input_tokens 含大量缓存命中），累加会
    重复计算系统提示。取第一轮最接近用户感知的单次用量。
    """
    for u in parts:
        if u and (u.input_tokens or u.output_tokens):
            return u
    return Usage()


def sum_usage(parts: list[Usage | None]) -> Usage:
    """累加所有 usage（保留首个 model/provider）。"""
    total = Usage()
    for u in parts:
        if u:
            total.add(u)
            if u.model and not total.model:
                total.model = u.model
            if u.provider and not total.provider:
                total.provider = u.provider
    return total


def messages_to_prompt(messages: list[dict[str, Any]]) -> str:
    """把 OpenAI/Anthropic 风格 messages 拍平成单条文本（用于估算 & 注入上游）。"""
    parts: list[str] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = " ".join(
                (c.get("text") if isinstance(c, dict) else str(c)) for c in content if c
            )
        else:
            text = str(content)
        parts.append(f"[{role}]\n{text}")
    return "\n\n".join(parts)
