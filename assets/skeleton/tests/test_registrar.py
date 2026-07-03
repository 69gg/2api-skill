"""注册机通用组件测试（不依赖网络）。"""
from __future__ import annotations

import json
from typing import Any

from registrar.email_client import create_email
from registrar.models import load_registrar_config


def test_registrar_config_reads_upstream(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[upstream]\nsupabase_url = "https://x.supabase.co"\nsupabase_anon_key = "anon"\n'
        '[email]\nbase_url = "https://mail.example.com"\nadmin_auth = "a"\n'
        '[captcha]\nmethod = "semi"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TWOAPI_CONFIG", str(cfg))
    rc = load_registrar_config()
    assert rc.upstream == {"supabase_url": "https://x.supabase.co", "supabase_anon_key": "anon"}


class _FakeHttpClient:
    """捕获 post_json 调用并返回固定响应。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    def post_json(self, url: str, body: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        self.calls.append((url, body, headers or {}))
        return {
            "status_code": 200,
            "text": json.dumps({"address": "x@example.com", "jwt": "jwt"}),
        }


def test_create_email_generates_name_when_empty():
    http = _FakeHttpClient()
    result = create_email(
        http, "https://mail.example.com",
        admin_auth="admin",
        custom_auth="",
        domain="example.com",
        name="",
    )
    assert result["address"] == "x@example.com"
    assert len(http.calls) == 1
    body = http.calls[0][1]
    assert body["name"]
    assert len(body["name"]) >= 8
    assert body["domain"] == "example.com"
    assert body["enablePrefix"] is False


def test_create_email_uses_provided_name():
    http = _FakeHttpClient()
    create_email(http, "https://mail.example.com", admin_auth="admin", name="myname")
    assert http.calls[0][1]["name"] == "myname"
