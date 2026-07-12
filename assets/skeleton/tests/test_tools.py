"""tools 测试：三级解析、tolerant_parse、strip、directive、拒绝跳过、真流式状态机。"""
from __future__ import annotations

from app.tools import (
    ToolCallStreamParser,
    ToolDef,
    build_tool_directive,
    parse_tool_calls,
    strip_tool_calls,
    tolerant_parse,
)


def test_parse_fenced_json_aware():
    # 围栏体内含 } 字面量（在字符串里），JSON-aware 不误截断
    text = '<tool_call>{"name": "f", "arguments": {"code": "a}b"}}</tool_call>'
    calls = parse_tool_calls(text, known_names={"f"})
    assert len(calls) == 1
    assert calls[0].name == "f"
    assert calls[0].arguments == {"code": "a}b"}


def test_parse_markdown_block():
    text = '```json\n{"name": "g", "arguments": {"x": 1}}\n```'
    calls = parse_tool_calls(text)
    assert len(calls) == 1
    assert calls[0].name == "g"


def test_parse_bare_json_needs_whitelist():
    # 裸 JSON 必须命中白名单
    assert parse_tool_calls('{"name": "f", "arguments": {}}', known_names={"f"})
    assert not parse_tool_calls('{"name": "f", "arguments": {}}')  # 无白名单不采纳裸 JSON


def test_parse_dedup():
    text = ('<tool_call>{"name": "f", "arguments": {"a": 1}}</tool_call>\n'
            '<tool_call>{"name": "f", "arguments": {"a": 1}}</tool_call>')
    assert len(parse_tool_calls(text, known_names={"f"})) == 1


def test_parse_refusal_skips(tmp_path, monkeypatch):
    """refusal_detect=true 时跳过含拒绝措辞的假阳性 tool_call；默认关时仍解析。"""
    from app.config import clear_settings_cache

    text = 'I can\'t do that. <tool_call>{"name":"f","arguments":{}}</tool_call>'
    cfg = tmp_path / "config.toml"
    cfg.write_text("[upstream]\nrefusal_detect = false\n", encoding="utf-8")
    monkeypatch.setenv("TWOAPI_CONFIG", str(cfg))
    clear_settings_cache()
    assert len(parse_tool_calls(text, known_names={"f"})) == 1

    cfg.write_text("[upstream]\nrefusal_detect = true\n", encoding="utf-8")
    clear_settings_cache()
    assert parse_tool_calls(text, known_names={"f"}) == []



def test_tolerant_parse_unclosed_and_trailing_comma():
    assert tolerant_parse('{"a": 1,') == {"a": 1}
    assert tolerant_parse('{"a": "unterminated') == {"a": "unterminated"}
    assert tolerant_parse('{"x": 1}\n') == {"x": 1}


def test_strip_tool_calls():
    text = 'before <tool_call>{"name":"f","arguments":{}}</tool_call> after'
    assert strip_tool_calls(text) == "before  after"


def test_build_directive_variants():
    tools = [ToolDef(name="f", description="d", parameters={"type": "object"})]
    assert build_tool_directive([]) == ""
    d = build_tool_directive(tools)
    r = build_tool_directive(tools, variant="retry")
    assert "<tool_call>" in d and '"f"' in d
    assert d != r
    assert "fixture" in r.lower()


def test_stream_parser_cross_chunk():
    p = ToolCallStreamParser(known_names={"get_weather"})
    out: list = []
    for chunk in ["<tool_ca", 'll>{"name": "get_weather", "arguments": {"city": "x"}}</tool_call>']:
        out.extend(p.feed(chunk))
    out.extend(p.finish())
    tools = [v for k, v in out if k == "tool"]
    texts = [v for k, v in out if k == "text"]
    assert len(tools) == 1
    assert tools[0].name == "get_weather"
    assert tools[0].arguments == {"city": "x"}
    # 半截 tag 不应当文本吐出
    assert all("<tool_ca" not in t for t in texts)


def test_stream_parser_plain_text():
    p = ToolCallStreamParser()
    out: list = []
    for chunk in ["hello", " world"]:
        out.extend(p.feed(chunk))
    out.extend(p.finish())
    text = "".join(v for k, v in out if k == "text")
    assert text == "hello world"
    assert not any(k == "tool" for k, _ in out)


def test_stream_parser_unclosed_fence():
    # 围栏未闭合（被截断）→ finish 时尽力解析
    p = ToolCallStreamParser(known_names={"f"})
    out = p.feed('<tool_call>{"name": "f", "arguments": {"a": 1}}')
    out.extend(p.finish())
    tools = [v for k, v in out if k == "tool"]
    assert len(tools) == 1
    assert tools[0].arguments == {"a": 1}
