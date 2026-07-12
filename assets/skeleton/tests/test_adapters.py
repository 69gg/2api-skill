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


# ─── reasoning / thinking 透传（上游有则按标准格式返回）──────────────────────


def _thinking_provider():
    """thinking + text + finish（含 thinking_tokens）。"""
    from app.events import Usage

    return FakeProvider([
        IREvent(kind="thinking", thinking="先分析问题"),
        IREvent(kind="thinking", thinking="再给答案"),
        IREvent(kind="text", text="结论是42"),
        IREvent(kind="finish", finish_reason="stop",
                usage_delta=Usage(input_tokens=10, output_tokens=8, thinking_tokens=5)),
    ])


def test_chat_reasoning_non_stream(app):
    """Chat 非流式：message.reasoning_content + completion_tokens_details.reasoning_tokens。"""
    _override(app, _thinking_provider())
    with TestClient(app) as client:
        r = client.post("/v1/chat/completions",
                        json={"model": "x", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    msg = r.json()["choices"][0]["message"]
    assert msg["content"] == "结论是42"
    assert msg["reasoning_content"] == "先分析问题再给答案"
    usage = r.json()["usage"]
    assert usage["completion_tokens_details"]["reasoning_tokens"] == 5


def test_chat_reasoning_stream(app):
    """Chat 流式：delta.reasoning_content 帧存在。"""
    import json as _json

    _override(app, _thinking_provider())
    with TestClient(app) as client:
        with client.stream("POST", "/v1/chat/completions",
                           json={"model": "x", "stream": True,
                                 "messages": [{"role": "user", "content": "hi"}]}) as r:
            body = b"".join(r.iter_bytes()).decode()
    assert "reasoning_content" in body
    assert "先分析问题" in body
    assert "结论是42" in body
    # 解析 SSE 确认 delta 字段
    saw_reasoning = False
    for line in body.splitlines():
        if not line.startswith("data: ") or line.strip() == "data: [DONE]":
            continue
        obj = _json.loads(line[6:])
        delta = (obj.get("choices") or [{}])[0].get("delta") or {}
        if delta.get("reasoning_content"):
            saw_reasoning = True
    assert saw_reasoning


def test_chat_reasoning_with_tool_calls(app):
    """Chat tool 路径：reasoning_content 与 tool_calls 并存。"""
    provider = FakeProvider([
        IREvent(kind="thinking", thinking="需要调工具"),
        IREvent(kind="text",
                text='<tool_call>{"name": "get_weather", "arguments": {"city": "x"}}</tool_call>'),
        IREvent(kind="finish", finish_reason="stop"),
    ])
    _override(app, provider)
    tools = [{"type": "function", "function": {
        "name": "get_weather", "description": "", "parameters": {"type": "object", "properties": {}} }}]
    with TestClient(app) as client:
        r = client.post("/v1/chat/completions",
                        json={"model": "x", "messages": [{"role": "user", "content": "weather"}],
                              "tools": tools})
    data = r.json()
    msg = data["choices"][0]["message"]
    assert data["choices"][0]["finish_reason"] == "tool_calls"
    assert msg["reasoning_content"] == "需要调工具"
    assert msg["tool_calls"][0]["function"]["name"] == "get_weather"
    assert msg["content"] is None


def test_responses_reasoning_non_stream(app):
    """Responses 非流式：output 含 type=reasoning 项。"""
    _override(app, _thinking_provider())
    with TestClient(app) as client:
        r = client.post("/v1/responses", json={"model": "x", "input": "hi"})
    assert r.status_code == 200
    out = r.json()["output"]
    types = [o.get("type") for o in out]
    assert "reasoning" in types
    assert "message" in types
    reasoning = next(o for o in out if o["type"] == "reasoning")
    assert reasoning["summary"][0]["text"] == "先分析问题再给答案"
    usage = r.json()["usage"]
    assert usage["output_tokens_details"]["reasoning_tokens"] == 5


def test_responses_reasoning_stream(app):
    """Responses 流式：reasoning_item / reasoning_summary_text 事件。"""
    _override(app, _thinking_provider())
    with TestClient(app) as client:
        with client.stream("POST", "/v1/responses",
                           json={"model": "x", "stream": True, "input": "hi"}) as r:
            body = b"".join(r.iter_bytes()).decode()
    assert "response.reasoning_item.added" in body
    assert "response.reasoning_summary_text.delta" in body
    assert "response.reasoning_item.done" in body
    assert "先分析问题" in body
    assert "结论是42" in body


def test_responses_reasoning_with_tools(app):
    """Responses tool 路径：reasoning 与 function_call 并列，不丢 thinking。"""
    provider = FakeProvider([
        IREvent(kind="thinking", thinking="查天气"),
        IREvent(kind="text",
                text='<tool_call>{"name": "get_weather", "arguments": {"city": "x"}}</tool_call>'),
        IREvent(kind="finish", finish_reason="stop"),
    ])
    _override(app, provider)
    tools = [{"type": "function", "function": {
        "name": "get_weather", "description": "", "parameters": {"type": "object", "properties": {}} }}]
    with TestClient(app) as client:
        r = client.post("/v1/responses",
                        json={"model": "x", "input": "weather", "tools": tools})
    out = r.json()["output"]
    types = [o.get("type") for o in out]
    assert "reasoning" in types
    assert "function_call" in types
    assert next(o for o in out if o["type"] == "reasoning")["summary"][0]["text"] == "查天气"


def test_anthropic_reasoning_non_stream(app):
    """Anthropic 非流式：content 含 type=thinking block。"""
    _override(app, _thinking_provider())
    with TestClient(app) as client:
        r = client.post("/v1/messages",
                        json={"model": "x", "messages": [{"role": "user", "content": "hi"}],
                              "max_tokens": 100})
    assert r.status_code == 200
    content = r.json()["content"]
    types = [c.get("type") for c in content]
    assert types[0] == "thinking"
    assert content[0]["thinking"] == "先分析问题再给答案"
    assert content[0]["signature"] == ""
    assert types[-1] == "text"
    assert content[-1]["text"] == "结论是42"
    assert r.json()["usage"]["thinking_tokens"] == 5


def test_anthropic_reasoning_stream(app):
    """Anthropic 流式：thinking_delta content_block 序列。"""
    import json as _json

    _override(app, _thinking_provider())
    with TestClient(app) as client:
        with client.stream("POST", "/v1/messages",
                           json={"model": "x", "stream": True, "max_tokens": 100,
                                 "messages": [{"role": "user", "content": "hi"}]}) as r:
            body = b"".join(r.iter_bytes()).decode()
    assert "thinking_delta" in body
    assert "先分析问题" in body
    assert "结论是42" in body
    # 一个 thinking block：start → delta(s) → stop，而非每 delta 开新 block
    events: list[str] = []
    for line in body.splitlines():
        if line.startswith("event: "):
            events.append(line[7:].strip())
    # 至少有 content_block_start / delta / stop
    assert events.count("content_block_start") >= 2  # thinking + text
    assert "content_block_delta" in events
    assert "content_block_stop" in events
    # 解析确认 thinking_delta
    saw_thinking_delta = False
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        obj = _json.loads(line[6:])
        delta = obj.get("delta") or {}
        if delta.get("type") == "thinking_delta":
            saw_thinking_delta = True
    assert saw_thinking_delta


def test_anthropic_reasoning_with_tool_use(app):
    """Anthropic tool 路径：thinking 与 tool_use 并列。"""
    provider = FakeProvider([
        IREvent(kind="thinking", thinking="需要工具"),
        IREvent(kind="text",
                text='<tool_call>{"name": "get_weather", "arguments": {"city": "x"}}</tool_call>'),
        IREvent(kind="finish", finish_reason="stop"),
    ])
    _override(app, provider)
    tools = [{"name": "get_weather", "description": "",
              "input_schema": {"type": "object", "properties": {}}}]
    with TestClient(app) as client:
        r = client.post("/v1/messages",
                        json={"model": "x", "messages": [{"role": "user", "content": "weather"}],
                              "max_tokens": 100, "tools": tools})
    data = r.json()
    assert data["stop_reason"] == "tool_use"
    types = [c.get("type") for c in data["content"]]
    assert "thinking" in types
    assert "tool_use" in types
    assert data["content"][0]["thinking"] == "需要工具"


def test_extract_user_prompt_preserves_reasoning():
    """入站 history 的 reasoning_content / thinking block 不得丢弃。"""
    from app.adapters import extract_user_prompt

    prompt = extract_user_prompt([
        {"role": "assistant", "content": "答案", "reasoning_content": "思考过程"},
        {"role": "user", "content": "继续"},
    ])
    assert "思考过程" in prompt
    assert "<reasoning>" in prompt

    prompt2 = extract_user_prompt([
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "内部推理"},
            {"type": "text", "text": "回复"},
        ]},
        {"role": "user", "content": "ok"},
    ])
    assert "内部推理" in prompt2
    assert "<thinking>" in prompt2


def test_extract_user_prompt_default_identity_when_no_system():
    """无 system 时注入缺省身份：真实 model id + 禁止提及平台。"""
    from app.adapters import extract_user_prompt
    from app.system_sanitizer import PLATFORM_NAME, default_identity_system

    prompt = extract_user_prompt(
        [{"role": "user", "content": "hi"}],
        model_id="claude-sonnet-4",
    )
    assert "`claude-sonnet-4`" in prompt
    assert "Do not mention" in prompt
    assert PLATFORM_NAME in prompt or "host platform" in prompt
    assert "[user]\nhi" in prompt
    # 缺省身份应位于用户消息之前
    assert prompt.index("claude-sonnet-4") < prompt.index("[user]")
    # 与模板一致
    assert default_identity_system("claude-sonnet-4") in prompt


def test_extract_user_prompt_no_default_when_system_present():
    """有客户端 system 时不注入缺省身份，且不覆盖实质指令。"""
    from app.adapters import extract_user_prompt

    prompt = extract_user_prompt(
        [
            {"role": "system", "content": "你是一个简洁的助手。"},
            {"role": "user", "content": "hi"},
        ],
        model_id="claude-sonnet-4",
    )
    assert "你是一个简洁的助手" in prompt
    assert "Do not mention" not in prompt
    assert "`claude-sonnet-4`" not in prompt


def test_extract_user_prompt_soften_off_by_default():
    """默认不软化 system：无柔和背景包装。"""
    from app.adapters import extract_user_prompt

    prompt = extract_user_prompt(
        [
            {"role": "system", "content": "You must always answer in French."},
            {"role": "user", "content": "hi"},
        ],
        model_id=None,
        soften=False,
    )
    assert "You must always answer in French." in prompt
    assert "for reference" not in prompt.lower()
    assert "Background context" not in prompt


def test_extract_user_prompt_soften_on_wraps():
    """soften=True 时走软化包装，实质指令仍保留。"""
    from app.adapters import extract_user_prompt

    body = "You must always answer in French."
    prompt = extract_user_prompt(
        [{"role": "system", "content": body}, {"role": "user", "content": "hi"}],
        model_id=None,
        soften=True,
    )
    assert body in prompt
    assert "Background context" in prompt or "for reference" in prompt.lower()


def test_extract_user_prompt_empty_system_gets_default():
    """空 system / 纯空白 / 纯垃圾元数据行视为无 system，仍注入缺省身份。"""
    from app.adapters import extract_user_prompt

    for sys_content in ("   ", "x-anthropic-billing-header: secret\n"):
        prompt = extract_user_prompt(
            [
                {"role": "system", "content": sys_content},
                {"role": "user", "content": "hi"},
            ],
            model_id="gpt-4o",
        )
        assert "`gpt-4o`" in prompt, repr(sys_content)
        assert "Do not mention" in prompt, repr(sys_content)


def test_chat_injects_default_identity_into_upstream_prompt(app, text_provider):
    """端到端：无 system 的 chat 请求，上游 prompt 含 model id 与平台禁言。"""
    _override(app, text_provider)
    with TestClient(app) as client:
        r = client.post(
            "/v1/chat/completions",
            json={"model": "x", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert r.status_code == 200
    # 未知 model 归一化为 DEFAULT_MODEL
    from app.upstream.models import DEFAULT_MODEL

    assert text_provider.captured_prompt is not None
    assert f"`{DEFAULT_MODEL}`" in text_provider.captured_prompt
    assert "Do not mention" in text_provider.captured_prompt
