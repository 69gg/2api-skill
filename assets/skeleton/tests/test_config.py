"""配置层测试：toml 加载、段平铺、别名、文件缺失回退默认、lru_cache。"""
from __future__ import annotations

from app.config import Settings, get_settings


def test_missing_file_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("TWOAPI_CONFIG", str(tmp_path / "nope.toml"))
    s = get_settings()
    assert isinstance(s, Settings)
    assert s.gateway_api_key == ""
    assert s.admin_auth_key == ""
    assert s.upstream_strategy == "prompt"


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
