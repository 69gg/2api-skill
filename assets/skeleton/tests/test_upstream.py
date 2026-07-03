"""上游适配器测试模板：mock HTTP + 固定 SSE 流。

本文件给出测试 `app/upstream/` 的示例写法。占位实现会抛 `NotImplementedError`；
换目标网站实现 `auth/client/parser` 后，把这些示例改成真实断言即可。
"""
from __future__ import annotations

import httpx
import pytest

from app.account import AccountPool, FailReason
from app.events import IREvent
from app.upstream.auth import DefaultAuthProvider
from app.upstream.base import AuthProvider
from app.upstream.parser import DefaultParser
from app.upstream.provider import UpstreamProvider


class _DummyAccount:
    """auth provider 占位用的最小账号对象。"""

    name = "dummy"


def test_default_auth_detects_401_403():
    auth = DefaultAuthProvider(_DummyAccount(), None, None)  # type: ignore[arg-type]
    err401 = httpx.HTTPStatusError(
        "unauthorized",
        request=httpx.Request("GET", "https://example.com"),
        response=httpx.Response(401),
    )
    err403 = httpx.HTTPStatusError(
        "forbidden",
        request=httpx.Request("GET", "https://example.com"),
        response=httpx.Response(403),
    )
    err500 = httpx.HTTPStatusError(
        "server error",
        request=httpx.Request("GET", "https://example.com"),
        response=httpx.Response(500),
    )
    assert auth.is_auth_failure(err401) is True
    assert auth.is_auth_failure(err403) is True
    assert auth.is_auth_failure(err500) is False


def test_default_parser_placeholder_raises():
    parser = DefaultParser()
    with pytest.raises(NotImplementedError):
        parser.parse({"type": "text", "content": "hello"})


class _ExampleSSEParser:
    """示例 parser：把 `data: {"text":"..."}` 这种 SSE 单行解析成 IREvent。"""

    def parse(self, raw: dict[str, str]) -> list[IREvent]:
        if raw.get("type") == "text":
            return [IREvent(kind="text", text=raw.get("content", ""))]
        if raw.get("type") == "finish":
            return [IREvent(kind="finish", finish_reason="stop")]
        return []


async def test_mock_sse_stream_via_httpx():
    """用 ``httpx.MockTransport`` 伪造 SSE 流，演示如何测 client → parser 链路。"""
    sse_lines = [
        'data: {"type":"text","content":"你好"}',
        "",
        'data: {"type":"text","content":"，世界"}',
        "",
        'data: {"type":"finish"}',
        "",
    ]

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="\n".join(sse_lines),
            headers={"content-type": "text/event-stream"},
        )

    parser = _ExampleSSEParser()
    events: list[IREvent] = []
    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        async with client.stream("POST", "https://api.example.com/chat") as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    import json

                    raw = json.loads(line.removeprefix("data: "))
                    events.extend(parser.parse(raw))

    assert [e.kind for e in events] == ["text", "text", "finish"]
    assert "".join(e.text for e in events if e.kind == "text") == "你好，世界"


class _CustomAuth(AuthProvider):
    """示例：上游化错误分类。"""

    async def get_auth(self) -> dict[str, str]:
        return {}

    def is_auth_failure(self, exc: BaseException) -> bool:
        return False

    def classify_failure(self, exc: BaseException) -> FailReason | None:
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 418:
            return FailReason.BANNED
        return None


async def test_auth_provider_classify_failure_overrides(tmp_path):
    """自定义 AuthProvider.classify_failure 优先于 deps 通用逻辑。"""
    from app.deps import _RetryingClient

    d = tmp_path / "account"
    d.mkdir()
    (d / "x.json").write_text('{"name":"x"}', encoding="utf-8")
    pool = AccountPool.load(d)
    account = pool.all()[0]

    class FailingProvider:
        async def stream(self, *args, **kwargs):
            raise httpx.HTTPStatusError(
                "teapot",
                request=httpx.Request("GET", "https://example.com"),
                response=httpx.Response(418),
            )
            yield ""  # type: ignore[unreachable]  # 使本函数成为 async generator

    provider = UpstreamProvider(account, None, None, _CustomAuth(), FailingProvider())
    client = _RetryingClient(pool, account, provider)
    with pytest.raises(Exception):
        async for _ in client.stream("hi"):
            pass

    assert account.fail_reason == FailReason.BANNED
    assert account.disabled is True


async def test_quota_exhausted_marks_account(tmp_path):
    """模拟上游返回 429 quota exceeded，验证账号被标记 QUOTA_EXHAUSTED。"""
    from app.account import _COOLDOWN_SECONDS_MAP, set_cooldown_policy
    from app.deps import _RetryingClient

    _COOLDOWN_SECONDS_MAP.clear()
    set_cooldown_policy("cooldown")

    d = tmp_path / "account"
    d.mkdir()
    (d / "x.json").write_text('{"name":"x"}', encoding="utf-8")
    pool = AccountPool.load(d)
    account = pool.all()[0]

    class QuotaProvider:
        async def stream(self, *args, **kwargs):
            raise httpx.HTTPStatusError(
                "quota exceeded",
                request=httpx.Request("GET", "https://example.com"),
                response=httpx.Response(429, text="quota exceeded"),
            )
            yield ""  # type: ignore[unreachable]  # 使本函数成为 async generator

    provider = UpstreamProvider(
        account, None, None, DefaultAuthProvider(account, None, None), QuotaProvider()
    )
    client = _RetryingClient(pool, account, provider)
    with pytest.raises(Exception):
        async for _ in client.stream("hi"):
            pass

    assert account.fail_reason == FailReason.QUOTA_EXHAUSTED
    assert account.cooldown_until > 0


def test_balance_check_mock_pattern(tmp_path):
    """示例：mock /v1/teams/{id}/balance 余额检查并主动标记账号。"""
    import json
    import time

    from app.account import Account, FailReason

    # 模拟余额接口响应
    balance_response = {"team_id": "t1", "balance": 0, "currency": "USD"}

    def check_balance_and_mark(account: Account, pool: AccountPool) -> None:
        # 实际实现中这里用 httpx 请求上游 balance 接口
        if balance_response.get("balance", 1) <= 0:
            pool.mark_failed(account, FailReason.QUOTA_EXHAUSTED)

    d = tmp_path / "account"
    d.mkdir()
    (d / "a.json").write_text(json.dumps({"name": "a"}), encoding="utf-8")
    pool = AccountPool.load(d)
    account = pool.all()[0]

    check_balance_and_mark(account, pool)
    assert account.fail_reason == FailReason.QUOTA_EXHAUSTED
    assert account.cooldown_until > time.time()
