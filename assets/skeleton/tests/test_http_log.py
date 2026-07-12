"""http_log 脱敏、usage 提取与中间件访问日志测试。"""
from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient

from app.deps import get_client
from app.http_log import (
    extract_usage_from_body,
    format_body_for_log,
    redact_body_obj,
    redact_headers,
)


def test_redact_headers_masks_authorization() -> None:
    h = redact_headers({
        "Authorization": "Bearer 1345|abcdefghijklmnopqrstuvwxyz",
        "Content-Type": "application/json",
        "Cookie": "session=supersecrettokenvalue",
    })
    assert "Bearer" in h["Authorization"]
    assert "abcdefghijklmnopqrstuvwxyz" not in h["Authorization"]
    assert h["Content-Type"] == "application/json"
    assert "supersecrettokenvalue" not in h["Cookie"]


def test_redact_body_masks_token_fields() -> None:
    obj = redact_body_obj({
        "token": "secret-token-value",
        "password": "Password1",
        "model": "claude-haiku",
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert "secret-token-value" not in str(obj["token"])
    assert "Password1" not in str(obj["password"])
    assert obj["model"] == "claude-haiku"
    assert obj["messages"][0]["content"] == "hi"


def test_format_body_json_and_truncate() -> None:
    raw = b'{"model":"x","messages":[{"role":"user","content":"hello"}]}'
    s = format_body_for_log(raw, content_type="application/json")
    assert "hello" in s
    assert "model" in s


def test_format_body_data_url_shortened() -> None:
    data_url = "data:image/png;base64," + ("A" * 500)
    s = format_body_for_log(
        json.dumps({"url": data_url}),
        content_type="application/json",
    )
    assert "data_url" in s or "…" in s
    assert "A" * 100 not in s or "len=" in s


def test_extract_usage_from_openai_json() -> None:
    raw = json.dumps({
        "choices": [],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    })
    u = extract_usage_from_body(raw, content_type="application/json")
    assert u is not None
    assert u["prompt_tokens"] == 10
    assert u["total_tokens"] == 15


def test_extract_usage_from_sse() -> None:
    sse = (
        'data: {"id":"1","choices":[{"delta":{"content":"hi"}}]}\n\n'
        'data: {"usage":{"prompt_tokens":3,"completion_tokens":1,"total_tokens":4}}\n\n'
        "data: [DONE]\n\n"
    )
    u = extract_usage_from_body(sse, content_type="text/event-stream")
    assert u is not None
    assert u["total_tokens"] == 4


def test_middleware_logs_request_and_usage(app, text_provider, caplog):
    """端到端：中间件记录 header/body/elapsed/usage，且不把 Bearer 原文写出。"""
    app.dependency_overrides[get_client] = lambda: text_provider
    with caplog.at_level(logging.INFO, logger="app.http_log"):
        with TestClient(app) as client:
            r = client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer super-secret-key-value"},
                json={"model": "x", "messages": [{"role": "user", "content": "hi"}]},
            )
    assert r.status_code == 200
    assert "x-request-id" in r.headers
    text = caplog.text
    assert ">>>" in text and "<<<" in text
    assert "elapsed_ms=" in text
    assert "usage=" in text
    assert "super-secret-key-value" not in text
    assert "hi" in text  # request body content
    assert "你好" in text or "response body" in text


def test_middleware_skips_healthz(app, caplog):
    with caplog.at_level(logging.INFO, logger="app.http_log"):
        with TestClient(app) as client:
            r = client.get("/healthz")
    assert r.status_code == 200
    assert ">>>" not in caplog.text
