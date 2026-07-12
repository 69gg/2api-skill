"""拒绝检测开关：默认关，启用后 is_refusal 才命中。"""
from __future__ import annotations

from app.config import clear_settings_cache
from app.refusal import is_refusal, looks_refusal


def test_looks_refusal_pure_match() -> None:
    assert looks_refusal("I can't help with that")
    assert not looks_refusal("here is the weather")


def test_is_refusal_off_by_default(tmp_path, monkeypatch) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text("[upstream]\nrefusal_detect = false\n", encoding="utf-8")
    monkeypatch.setenv("TWOAPI_CONFIG", str(cfg))
    clear_settings_cache()
    assert is_refusal("I can't generate tool calls", has_tools=True) is False


def test_is_refusal_on_when_enabled(tmp_path, monkeypatch) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text("[upstream]\nrefusal_detect = true\n", encoding="utf-8")
    monkeypatch.setenv("TWOAPI_CONFIG", str(cfg))
    clear_settings_cache()
    assert is_refusal("I can't generate tool calls", has_tools=True) is True
    assert is_refusal("I can't generate tool calls", has_tools=False) is False
