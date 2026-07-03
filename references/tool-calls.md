# tool call 实现

> webchat 一般不暴露原生 function-calling，靠 prompt 注入 + 文本解析模拟。代码在 `app/tools.py`。

## 一、双模策略

`settings.upstream_strategy` 决定（默认 `prompt`）：

- **native 模式**：上游原生支持 function-calling 时，由 `app/upstream/client.py` 直接产 `IREvent(kind="tool", tool=ToolEvent(name, detail={"arguments": {...}}))`，adapter 直通成标准 tool_calls/tool_use，**不注入任何指令**。
- **prompt 模式**：上游不支持时，`build_tool_directive(tools)` 把 tools 定义注入消息最前，让上游产出围栏文本，再用 `parse_tool_calls` 解析回标准 tool_calls/tool_use。

`app/orchestrator.py` 按 `settings.upstream_strategy` 决定是否注入 directive；prompt 模式才注入。

## 二、指令模板（`app/tools.py:_DIRECTIVES`）

围栏标签 `OPEN_TAG = "<tool_call>"`、`CLOSE_TAG = "</tool_call>"`，让模型按下面格式输出工具调用：

```
<tool_call>{"name": "<tool_name>", "arguments": { ... }}</tool_call>
```

**default 变体**（首轮）：明确要求模型把工具调用包成上述围栏，并给出可用工具列表（name/description/parameters 的紧凑 JSON）。

**retry 变体**（首轮被拒绝时换用）：伪装成「为下游 dispatcher 测试套件生成期望输出 fixture」，把工具调用包装成 fixture 文本，弱化「伪造工具调用」色彩，降低上游 agent 的对抗刺激（参考 promptql2api 的认知重构角度）。

两个变体都禁止 prose/markdown 包裹，要求只输出围栏块；若无需工具则正常回复。

## 三、三级降级解析（`app/tools.py:parse_tool_calls`）

应对上游不严格按围栏输出：

1. **围栏（JSON-aware 平衡扫描）**：`_scan_fenced_body` 用字符串/转义状态机扫描，**字符串内的 `}` 与 `close_tag` 字面量不计入**，遇平衡 JSON 闭合或字符串外闭标签即停。免疫大 content 内的字面量提前截断。信任度高，不限白名单。
2. **markdown json 块**（` ```json ... ``` `）：信任度中。
3. **裸 JSON**：仅当传入 `known_names` 且 name 命中白名单、非数据文档特征键（`_DATA_DOC_KEYS = {items, data, results, ...}`）、长度 ≤600 时才采纳。

所有 JSON 解析走 `tolerant_parse`：容错字符串内裸控制字符、未闭合括号补全、尾逗号清理。字段名兼容 `name|tool`、`arguments|parameters|input`。同名同参数去重。

**拒绝跳过**：若文本命中 `looks_refusal`（拒绝措辞），直接返回空——上游拒绝时常引用围栏格式作解释，并非真实调用，避免假阳性。

## 四、真流式状态机（`app/tools.py:ToolCallStreamParser`）

上游真流式（逐 token 增量）时，围栏可能跨 chunk 到达（如 `<tool_ca` + `ll>{...}`），直接解析会漏掉半截 tag。状态机解决：

- **状态**：TEXT（普通文本）→ IN_FENCE（围栏体内）。
- **前缀缓冲**：TEXT 状态下，若末尾是 `OPEN_TAG` 的某个前缀（如 `<tool_ca`），用 `_hold_prefix` hold 住这些字符，不当作文本吐出，等下个 chunk 到达再判断是否成完整 tag。
- **围栏体内**：到达 `CLOSE_TAG` 才解析；或流结束（`finish()`）时未闭合围栏也尝试解析已有 body。
- **产出**：`feed(chunk)` 返回 `[("text", str), ("tool", ParsedToolCall)]` 列表，`finish()` 收尾。

伪流式（上游整块返回文本）则直接用 `parse_tool_calls(整块)`，无需状态机。

## 五、流式 tool call 输出

adapter 收到 IREvent(kind="text") 增量时：
1. 用 `ToolCallStreamParser.feed(text)` 增量解析。
2. text 增量经 `strip_tool_calls` 剥离围栏后作为 content 增量释放给客户端。
3. tool 增量按各家协议转成对应格式（OpenAI `tool_calls` chunk / Anthropic `tool_use` block / Responses `function_call_arguments.delta`）。

## 六、测试要点

- 围栏内含 `}` 字面量（在字符串里）→ JSON-aware 不误截断。
- 裸 JSON 必须命中白名单。
- 拒绝文本跳过解析。
- 同名同参数去重。
- 跨 chunk 切分（`<tool_ca`|`ll>{...}`、`{"name":"x","ar`|`guments":1}`）→ 不误吐半截 tag。
- 未闭合围栏 → finish 时尽力解析已有 body。
