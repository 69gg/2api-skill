# 流式实现

> SSE 格式、warmup/guard 双缓冲、safe_sse_stream。代码在 `app/streaming.py` 与各 adapter。

## 一、SSE 帧格式

OpenAI：`data: {json}\n\n`，末尾 `data: [DONE]\n\n`。
Anthropic：`event: <type>\ndata: {json}\n\n`（typed events）。
OpenAI Responses：`event: response.*\ndata: {json}\n\n`（typed events）。

## 二、真流式 vs 伪流式

- **真流式**：上游逐 token 返回（如 SSE）。adapter 用 `ToolCallStreamParser` 增量解析 tool call，逐块输出 text/tool 增量。
- **伪流式**：上游整块返回（如 GraphQL 轮询后一次性返回）。adapter 收到完整文本后逐块切片输出，或直接当一帧。tool call 用 `parse_tool_calls(整块)`。

两种都支持，由 `app/upstream/client.py` 的实现决定（parser 决定产多少个 IREvent、何时产）。

## 三、warmup/guard 双缓冲（`app/streaming.py:IncrementalStreamer`）

解决的问题：**拒绝文本泄漏给客户端**。若上游一开始就在输出拒绝文本，流式已开始就难收回了。

策略：
- **warmup**（默认 96 字符）：先缓冲预热文本，达阈值才释放。若在 warmup 阶段命中 `is_blocked` 回调（如 `looks_refusal`），丢弃已缓冲内容，不再释放。
- **guard**（默认 256 字符）：释放时永远保留尾部 guard 窗口，给跨 chunk 的清洗规则（如 `strip_tool_calls`、`strip_thinking_tags`）留上下文；超过 guard 强制放行。
- `finish()` 返回剩余全部（含 guard 窗口）。

用法：`push(chunk)` 返回可安全释放的文本，`finish()` 收尾。

## 四、跨 chunk 标签清洗

`strip_thinking_tags` 用 `indexOf`/`lastIndexOf` 而非非贪婪正则剥离 `<thinking>...</thinking>`，防止内容含字面量标签时误截断。配合 guard 窗口跨 chunk 清洗。

## 五、safe_sse_stream（`app/streaming.py`）

把 SSE 流中途异常转译成 error chunk，避免 ASGI 在响应已开始后崩溃：
- 正常 yield 各 chunk；
- 捕获异常 → `on_error` 回调产出符合目标协议的 error 帧 + `[DONE]`（OpenAI）/ error event（Anthropic）；
- 连接已断则吞掉二次错误。

各 adapter 可传自定义 `on_error` 产出符合自家协议的 error 帧。

## 六、退化循环检测（可选）

某些上游会陷入死循环（重复输出相同内容）。可在 `app/upstream/client.py` 里检测短 delta / HTML token 连续重复 N 次中止，防模型死循环（参考 cursor2api）。

## 七、测试要点

- warmup 未达阈值不释放；达阈值后（guard=0）全释放。
- guard 保留尾部窗口，finish 时补齐。
- 命中 `is_blocked` 前缀的文本被丢弃。
- safe_sse_stream 捕获中途异常并产出 error chunk + `[DONE]`。
