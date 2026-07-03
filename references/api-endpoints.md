# API 端点规范

> 实现四套 API + admin 端点时，对照本文确认字段与流式帧格式。骨架已实现，详见 `app/adapters/`。

## 一、/v1/models

`GET /v1/models` → `{ "object": "list", "data": [{"id","object":"model","owned_by"}] }`。

**模型列表来自 `app/upstream/models.py` 的 `MODEL_CATALOG`，必须实地探测后填入，勿硬编码**（用 `scripts/probe_catalog.py`）。详见 `references/upstream-adapters.md`。

## 二、/v1/chat/completions（OpenAI Chat Completions）

**请求**：`{model, messages, stream?, tools?}`。

**非流式响应**：
```json
{
  "id": "chatcmpl-...", "object": "chat.completion", "created": 1234567890, "model": "<id>",
  "choices": [{"index": 0, "message": {"role":"assistant", "content": "...", "reasoning_content": "...", "tool_calls": [{"id","type":"function","function":{"name","arguments(JSON string)"}}]}}, "finish_reason": "stop|tool_calls"}],
  "usage": {"prompt_tokens", "completion_tokens", "total_tokens"}
}
```

**流式响应**：SSE 帧 `data: {...}\n\n`，末尾 `data: [DONE]\n\n`：
- 首帧 `{"choices":[{"delta":{"role":"assistant"}}]}`。
- 正文：`{"choices":[{"delta":{"content":"增量"}}]}`。
- 思维链：`{"choices":[{"delta":{"reasoning_content":"..."}}]}`（DeepSeek 兼容）。
- tool call：`{"choices":[{"delta":{"tool_calls":[{"index","id","type":"function","function":{"name","arguments"}}]}}]}`。
- 末帧含 `finish_reason` 与 `usage`。

**关键点**：
- 有 tool_calls 时 `content` 设为 `null`，`finish_reason="tool_calls"`。
- tool call 的 `arguments` 是 JSON 字符串（非对象）。
- usage 真实优先，否则 `estimate_tokens` 估算（详见 `references/tokens-usage.md`）。

## 三、/v1/responses（OpenAI Responses）

**请求**：`{model, input, instructions?, stream?, tools?}`。`input` 可为字符串或 messages 数组。

**流式事件序列**（typed SSE）：
- `response.created` → `response.output_text.delta`（正文）→ `response.output_item.added`/`response.function_call_arguments.delta`/`response.output_item.done`（tool）→ `response.reasoning_item.added`/`response.reasoning_summary_text.delta`/`done`（思维链）→ `response.completed`。

**关键点**：prompt 模式下，prompt tool 输出会被**反向封装**成原生 `response.function_call_arguments.delta` 等事件，对外接口与原生一致。详见 `references/tool-calls.md`。

## 四、/v1/messages（Anthropic Messages）

**请求**：`{model, messages, system?, stream?, tools?, max_tokens?, thinking?}`。

**流式事件序列**：
- `message_start` → `content_block_start/delta/stop`（thinking block / text block / tool_use block 各一组）→ `message_delta`（含 `stop_reason` + `usage`）→ `message_stop`。

**非流式响应**：
```json
{
  "id": "msg_...", "type": "message", "role": "assistant", "model": "<id>",
  "content": [{"type":"text","text":"..."}],  // 或 [{"type":"thinking",...},{"type":"tool_use","id","name","input"}]
  "stop_reason": "end_turn|tool_use", "stop_sequence": null,
  "usage": {"input_tokens", "output_tokens"}
}
```

**关键点**：
- thinking → `content` 里加 `{"type":"thinking","thinking":...,"signature":""}`（signature 空串，上游不提供）。
- tool call → `{"type":"tool_use","id","name","input"}`，`stop_reason="tool_use"`。
- `system` 字段可被前置成一条 system message，与 messages 统一拍平。

## 五、/v1/messages/count_tokens

`POST /v1/messages/count_tokens` → `{ "input_tokens": <估算> }`。不调上游，纯估算。

## 六、/admin/*（账号管理）

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/admin/accounts` | 列摘要（name/source_email/created_at/disabled/fail_reason），**不暴露凭据字段** |
| GET | `/admin/accounts/{name}` | 单账号完整信息（含凭据，需 admin 鉴权） |
| POST | `/admin/accounts` | 上传/更新账号，原子写盘 + 同步内存池 + 构造 provider |
| DELETE | `/admin/accounts/{name}` | 删盘 + 移内存 + pop provider |
| POST | `/admin/reload` | 全量重读盘 + 重建全部 provider |

**鉴权**：`admin_auth_key` 留空 → 全部返回 **404**（隐藏端点存在）。校验 Bearer header 或 `?auth_key=` query 二选一。详见 `references/auth-and-errors.md`。

## 七、finish_reason 取值对照

| 场景 | OpenAI Chat | OpenAI Responses | Anthropic |
|---|---|---|---|
| 正常结束 | `stop` | `completed` | `end_turn` |
| tool call | `tool_calls` | `completed` | `tool_use` |
| 长度限制 | `length` | `incomplete` | `max_tokens` |
| 拒绝/错误 | `stop`（回退文本） | `failed` | `end_turn` |
