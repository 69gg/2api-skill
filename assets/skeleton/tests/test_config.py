"""配置层测试：toml 加载、段平铺、别名、文件缺失回退默认、lru_cache、代理解析。"""
from __future__ import annotations

from app.config import Settings, get_settings


def test_missing_file_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("TWOAPI_CONFIG", str(tmp_path / "nope.toml"))
    s = get_settings()
    assert isinstance(s, Settings)
    assert s.gateway_api_key == ""
    assert s.admin_auth_key == ""
    assert s.upstream_strategy == "prompt"
    assert s.proxy_url == ""
    assert s.registrar_proxy_url == ""
    assert s.effective_proxy() is None
    assert s.effective_registrar_proxy() is None


def test_flatten_and_aliases(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[gateway]\napi_key = "k1"\nport = 9000\n\n'
        '[admin]\nauth_key = "a1"\n\n'
        '[email]\nbase_url = "x"\n',  # [email] 应被忽略（仅注册机用）
        encoding="utf-8",
    )
    monkeypatch.setenv("TWOAPI_CONFIG", str(cfg))
    s = get_settings()
    assert s.gateway_api_key == "k1"  # api_key → gateway_api_key
    assert s.admin_auth_key == "a1"  # auth_key → admin_auth_key
    assert s.port == 9000
    # [email] 段不被主程序读取（无对应字段）
    assert not hasattr(s, "base_url")


def test_proxy_section_default_only(tmp_path, monkeypatch):
    """只配默认代理：网关与注册机都走它。"""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[proxy]\nurl = "http://127.0.0.1:7890"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TWOAPI_CONFIG", str(cfg))
    s = get_settings()
    assert s.proxy_url == "http://127.0.0.1:7890"
    assert s.registrar_proxy_url == ""
    assert s.effective_proxy() == "http://127.0.0.1:7890"
    assert s.effective_registrar_proxy() == "http://127.0.0.1:7890"


def test_proxy_section_registrar_overrides(tmp_path, monkeypatch):
    """注册机代理单独配置时不回落到默认。"""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[proxy]\nurl = "http://default:1"\nregistrar_url = "socks5://reg:2"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TWOAPI_CONFIG", str(cfg))
    s = get_settings()
    assert s.effective_proxy() == "http://default:1"
    assert s.effective_registrar_proxy() == "socks5://reg:2"


def test_proxy_blank_means_direct(tmp_path, monkeypatch):
    """空白字符串视为未配置，直连。"""
    cfg = tmp_path / "config.toml"
    cfg.write_text('[proxy]\nurl = "  "\nregistrar_url = ""\n', encoding="utf-8")
    monkeypatch.setenv("TWOAPI_CONFIG", str(cfg))
    s = get_settings()
    assert s.effective_proxy() is None
    assert s.effective_registrar_proxy() is None


def test_logging_section_maps_to_log_fields(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[logging]\n"
        "enabled = false\n"
        'dir = "mylogs"\n'
        'filename = "app.log"\n'
        'level = "DEBUG"\n'
        "max_bytes = 12345\n"
        "backup_count = 3\n"
        "log_request_body = false\n"
        "log_response_body = false\n"
        "max_body_chars = 100\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TWOAPI_CONFIG", str(cfg))
    s = get_settings()
    assert s.log_enabled is False
    assert s.log_dir == "mylogs"
    assert s.log_filename == "app.log"
    assert s.log_level == "DEBUG"
    assert s.log_max_bytes == 12345
    assert s.log_backup_count == 3
    assert s.log_request_body is False
    assert s.log_response_body is False
    assert s.log_max_body_chars == 100


def test_lru_cache_caches(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[gateway]\nport = 7000\n", encoding="utf-8")
    monkeypatch.setenv("TWOAPI_CONFIG", str(cfg))
    assert get_settings().port == 7000
    # 改文件但不清缓存 → 仍读旧值
    cfg.write_text("[gateway]\nport = 8000\n", encoding="utf-8")
    assert get_settings().port == 7000
    get_settings.cache_clear()
    assert get_settings().port == 8000
