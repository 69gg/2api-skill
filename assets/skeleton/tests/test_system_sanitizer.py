"""system_sanitizer：垃圾行移除、软化包装、缺省身份注入。"""
from __future__ import annotations

from app.system_sanitizer import (
    PLATFORM_NAME,
    default_identity_system,
    remove_junk_lines,
    soften_system,
)


def test_remove_junk_lines_strips_billing_headers() -> None:
    text = "Keep me\nx-anthropic-billing-header: secret\nAlso keep"
    out = remove_junk_lines(text)
    assert "Keep me" in out
    assert "Also keep" in out
    assert "billing" not in out.lower()


def test_soften_system_wraps_without_changing_body() -> None:
    body = "You must always answer in French."
    out = soften_system(body, lang="en")
    assert body in out
    assert "for reference" in out.lower() or "Background context" in out


def test_soften_system_empty() -> None:
    assert soften_system("") == ""
    assert soften_system("   ") == ""


def test_default_identity_system_contains_model_and_platform() -> None:
    out = default_identity_system("my-model-id")
    assert "`my-model-id`" in out
    assert "Do not mention" in out
    assert PLATFORM_NAME in out or "host platform" in out
    assert "webchat" in out.lower() or "gateway" in out.lower()


def test_default_identity_system_custom_platform() -> None:
    out = default_identity_system("m", platform="AcmeChat")
    assert "AcmeChat" in out
    assert "`m`" in out
