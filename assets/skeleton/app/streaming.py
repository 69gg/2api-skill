"""流式辅助：增量释放 warmup/guard 双缓冲 + safe_sse_stream 安全包装。

**warmup/guard 双缓冲**（参考 cursor2api streaming-text）：先缓冲预热文本，确认不是应拦截
的前缀（如拒绝文本）再开始释放；释放时永远保留尾部 guard 窗口，给跨 chunk 的清洗规则留
上下文；超过 guard 强制放行。避免「拒绝文本泄漏给客户端」。

**safe_sse_stream**（参考 grok2api）：把 SSE 流中途异常转译成 error chunk，避免 ASGI 在
响应已开始后崩溃（连接已关则吞掉二次错误）。
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Callable

DEFAULT_WARMUP = 96
DEFAULT_GUARD = 256


class IncrementalStreamer:
    """增量释放器：warmup 预热 + guard 尾部缓冲。

    - :meth:`push` 返回当前可安全释放给客户端的文本。
    - :meth:`finish` 返回剩余全部（含 guard 窗口）。
    - ``is_blocked`` 回调在 warmup 阶段判断文本是否为应拦截的前缀（如拒绝）。
    """

    def __init__(
        self,
        *,
        warmup: int = DEFAULT_WARMUP,
        guard: int = DEFAULT_GUARD,
        is_blocked: Callable[[str], bool] | None = None,
    ) -> None:
        self._warmup = warmup
        self._guard = guard
        self._is_blocked = is_blocked or (lambda _: False)
        self._buf: list[str] = []
        self._buflen = 0
        self._unlocked = False  # warmup 通过后置 True

    def push(self, chunk: str) -> str:
        """喂入一段文本，返回可释放的部分（可能为空，因 warmup/guard 缓冲）。"""
        if not chunk:
            return ""
        self._buf.append(chunk)
        self._buflen += len(chunk)
        if not self._unlocked:
            if self._buflen < self._warmup:
                return ""
            head = "".join(self._buf)
            if self._is_blocked(head):
                # 命中拦截前缀（拒绝）：丢弃已缓冲，不再释放
                self._buf.clear()
                self._buflen = 0
                return ""
            self._unlocked = True
        # 释放时保留尾部 guard 窗口
        full = "".join(self._buf)
        if len(full) <= self._guard:
            return ""
        release_len = len(full) - self._guard
        self._buf = [full[release_len:]]
        self._buflen = len(self._buf[0])
        return full[:release_len]

    def finish(self) -> str:
        """收尾：返回剩余全部文本（若全程未过 warmup，最后再判一次拦截前缀）。"""
        if not self._unlocked:
            head = "".join(self._buf)
            if head and self._is_blocked(head):
                self._buf.clear()
                self._buflen = 0
                return ""
            self._unlocked = True
        out = "".join(self._buf)
        self._buf.clear()
        self._buflen = 0
        return out


def safe_sse_stream(
    stream: AsyncIterator[str],
    *,
    on_error: Callable[[BaseException], list[str]] | None = None,
) -> AsyncIterator[str]:
    """包装 SSE 流：正常 yield；中途异常 → on_error 产出的 chunk（默认通用 OpenAI 风格 error + [DONE]）。

    各 adapter 可传入自定义 ``on_error`` 以产出符合自家协议的 error 帧。
    """

    async def _gen() -> AsyncIterator[str]:
        try:
            async for chunk in stream:
                yield chunk
        except Exception as e:  # noqa: BLE001
            chunks = on_error(e) if on_error else [
                f'data: {{"error":{{"message":"{str(e)[:200]}"}}}}\n\n',
                "data: [DONE]\n\n",
            ]
            for c in chunks:
                try:
                    yield c
                except Exception:  # noqa: BLE001  连接已断，吞掉二次错误
                    break

    return _gen()
