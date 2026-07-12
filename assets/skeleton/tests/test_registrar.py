"""注册机通用组件测试（不依赖网络）。"""
from __future__ import annotations

import json
from typing import Any

from registrar.email_client import (
    _FAKE_EMAIL_DOMAINS,
    create_email,
    generate_random_email,
    random_localpart,
)
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
    assert rc.proxy_url == ""
    assert rc.effective_proxy() is None


def test_registrar_proxy_falls_back_to_default(tmp_path, monkeypatch):
    """注册机未单独配代理时回退 [proxy].url，并写入 captcha.proxy_url。"""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[proxy]\nurl = "http://gw:7890"\n'
        '[email]\nbase_url = "https://mail.example.com"\n'
        '[captcha]\nmethod = "semi"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TWOAPI_CONFIG", str(cfg))
    rc = load_registrar_config()
    assert rc.proxy_url == "http://gw:7890"
    assert rc.effective_proxy() == "http://gw:7890"
    assert rc.captcha.proxy_url == "http://gw:7890"


def test_registrar_proxy_overrides_default(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[proxy]\nurl = "http://gw:1"\nregistrar_url = "http://reg:2"\n'
        '[captcha]\nmethod = "semi"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TWOAPI_CONFIG", str(cfg))
    rc = load_registrar_config()
    assert rc.proxy_url == "http://reg:2"
    assert rc.captcha.proxy_url == "http://reg:2"


def test_captcha_proxy_url_not_overwritten(tmp_path, monkeypatch):
    """[captcha].proxy_url 显式配置时不被 [proxy] 覆盖。"""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[proxy]\nurl = "http://gw:1"\nregistrar_url = "http://reg:2"\n'
        '[captcha]\nmethod = "semi"\nproxy_url = "http://captcha:3"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TWOAPI_CONFIG", str(cfg))
    rc = load_registrar_config()
    assert rc.proxy_url == "http://reg:2"
    assert rc.captcha.proxy_url == "http://captcha:3"


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
    assert body["name"][0].isalpha()
    assert body["domain"] == "example.com"
    assert body["enablePrefix"] is False


def test_create_email_uses_provided_name():
    http = _FakeHttpClient()
    create_email(http, "https://mail.example.com", admin_auth="admin", name="myname")
    assert http.calls[0][1]["name"] == "myname"


def test_random_localpart_is_diverse():
    samples = {random_localpart() for _ in range(40)}
    assert len(samples) >= 38  # 高熵，几乎不撞
    for s in samples:
        assert s[0].isalpha()
        assert s.isalnum()


def test_generate_random_email_rotates_domains():
    """无需 OTP 时多域名轮换，不应用死单一 domain。"""
    addrs = [generate_random_email() for _ in range(80)]
    domains = {a.split("@", 1)[1] for a in addrs}
    assert len(domains) >= 5  # 80 次应覆盖多个域名
    assert domains <= set(_FAKE_EMAIL_DOMAINS)
    for a in addrs:
        local, dom = a.split("@", 1)
        assert local[0].isalpha()
        assert "@" not in local
        assert "." in dom


def test_generate_random_email_fixed_domain():
    a = generate_random_email(domain="example.test")
    assert a.endswith("@example.test")
    assert a.split("@")[0][0].isalpha()
