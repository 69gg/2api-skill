"""adapters 测试：三家 API（chat/responses/messages）流式+非流式+tool call，v1 key 校验。

用 FakeProvider（喂 IREvent 序列）通过 dependency_overrides 注入，不依赖真实上游。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.deps import get_client
from app.events import IREvent
from tests.conftest import FakeProvider


def _override(app, provider):
    app.dependency_overrides[get_client] = lambda: provider


def test_chat_non_stream(app, text_provider):
    _override(app, text_provider)
    with TestClient(app) as client:
        r = client.post("/v1/chat/completions",
                        json={"model": "x", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    data = r.json()
    assert data["choices"][0]["message"]["content"] == "你好，世界"
    assert data["usage"]["total_tokens"] >= 1


def test_chat_stream(app, text_provider):
    _override(app, text_provider)
    with TestClient(app) as client:
        with client.stream("POST", "/v1/chat/completions",
                           json={"model": "x", "stream": True,
                                 "messages": [{"role": "user", "content": "hi"}]}) as r:
            body = b"".join(r.iter_bytes())
    assert b"data: " in body
    assert b"[DONE]" in body
    assert "你好".encode() in body


def test_chat_tool_call(app):
    provider = FakeProvider([
        IREvent(kind="text", text='<tool_call>{"name": "get_weather", "arguments": {"city": "x"}}</tool_call>'),
        IREvent(kind="finish", finish_reason="stop"),
    ])
    _override(app, provider)
    tools = [{"type": "function", "function": {
        "name": "get_weather", "description": "", "parameters": {"type": "object", "properties": {}}}}]
    with TestClient(app) as client:
        r = client.post("/v1/chat/completions",
                        json={"model": "x", "messages": [{"role": "user", "content": "weather"}], "tools": tools})
    data = r.json()
    assert data["choices"][0]["finish_reason"] == "tool_calls"
    assert data["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "get_weather"


def test_responses_non_stream(app, text_provider):
    _override(app, text_provider)
    with TestClient(app) as client:
        r = client.post("/v1/responses", json={"model": "x", "input": "hi"})
    assert r.status_code == 200
    out = r.json()["output"]
    msg = [o for o in out if o.get("type") == "message"][0]
    assert "你好" in msg["content"][0]["text"]


def test_anthropic_messages_non_stream(app, text_provider):
    _override(app, text_provider)
    with TestClient(app) as client:
        r = client.post("/v1/messages",
                        json={"model": "x", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 100})
    assert r.status_code == 200
    data = r.json()
    assert data["content"][-1]["type"] == "text"
    assert data["content"][-1]["text"] == "你好，世界"


def test_count_tokens(app):
    with TestClient(app) as client:
        r = client.post("/v1/messages/count_tokens",
                        json={"model": "x", "messages": [{"role": "user", "content": "hello"}]})
    assert r.status_code == 200
    assert r.json()["input_tokens"] >= 1


def test_verify_api_key_enforced(app, text_provider):
    _override(app, text_provider)
    with TestClient(app) as client:
        app.state.settings.gateway_api_key = "secret"
        body = {"model": "x", "messages": [{"role": "user", "content": "hi"}]}
        # 无 key → 401
        assert client.post("/v1/chat/completions", json=body).status_code == 401
        # 错 key → 401
        h = {"Authorization": "Bearer wrong"}
        assert client.post("/v1/chat/completions", json=body, headers=h).status_code == 401
        # 对 key → 200
        h2 = {"Authorization": "Bearer secret"}
        assert client.post("/v1/chat/completions", json=body, headers=h2).status_code == 200


def test_models_endpoint(app):
    with TestClient(app) as client:
        r = client.get("/v1/models")
    assert r.status_code == 200
    assert r.json()["object"] == "list"
