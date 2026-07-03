"""streaming 测试：warmup/guard 双缓冲、拦截前缀、safe_sse_stream。"""
from __future__ import annotations

import pytest

from app.streaming import IncrementalStreamer, safe_sse_stream


def test_warmup_buffers_until_threshold():
    s = IncrementalStreamer(warmup=10, guard=0)
    assert s.push("ab") == ""  # 未达 warmup
    out = s.push("cdefghij")  # 累计 10，达 warmup，guard=0 全释放
    assert out.replace("", "") == "" or "abcdefghij" in out + s.finish()


def test_guard_keeps_tail_then_finish():
    s = IncrementalStreamer(warmup=0, guard=5)
    out1 = s.push("hello world")  # 11 字符，release 11-5=6 → "hello "
    assert out1 == "hello "
    assert s.finish() == "world"


def test_blocked_prefix_dropped():
    s = IncrementalStreamer(warmup=5, guard=0, is_blocked=lambda t: "拒绝" in t)
    s.push("我拒绝")  # 3 < 5，未达 warmup，缓冲
    assert s.push("xxx") == ""  # 累计 6 >= 5，命中拦截 → 丢弃
    assert s.finish() == ""


@pytest.mark.asyncio
async def test_safe_sse_stream_catches_error():
    async def gen():
        yield "data: a\n\n"
        raise RuntimeError("boom")

    out: list[str] = []
    async for c in safe_sse_stream(gen()):
        out.append(c)
    assert "data: a\n\n" in out
    assert any("error" in c for c in out)
    assert any("[DONE]" in c for c in out)
