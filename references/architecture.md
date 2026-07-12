# 通用 2api 架构蓝图

> 生成新 2api 项目时，通读本文理解整体分层与核心数据契约 IREvent。

## 一、整体分层

```
┌──────────────────────────────────────────────────────┐
│  FastAPI 入口 (app/main.py)                            │
│  lifespan：加载账号池 → 为每号建 UpstreamProvider → app.state │
├──────────────────────────────────────────────────────┤
│  API adapter 层 (app/adapters/)                        │
│  openai_models / openai_chat / openai_responses /      │
│  anthropic_messages  ←→ 各家标准格式                    │
├──────────────────────────────────────────────────────┤
│  编排层 (app/orchestrator.py)                          │
│  stream_with_retry：buffer；可选拒绝检测 + tool 变体重试 │
├──────────────────────────────────────────────────────┤
│  上游适配层 (app/upstream/)  ← 换目标网站时只改这里        │
│  auth.py / client.py / parser.py / models.py / provider.py │
├──────────────────────────────────────────────────────┤
│  账号池 / 配置 / 依赖注入 (app/account.py / config.py / deps.py) │
│  admin (app/admin.py)                                  │
│  日志：logging_setup + http_log 中间件（脱敏访问日志 / 轮转）   │
└──────────────────────────────────────────────────────┘
旁路：registrar/（独立包，单向 import app.account）
```

**代理**（`[proxy]`）：`url` 给网关 `httpx.AsyncClient`；`registrar_url` 给注册机（空则回退 `url`）；皆空直连。见 `project-conventions.md`。

**日志**（`[logging]`）：`setup_logging` 挂控制台 + 可选 `logs/` 轮转文件；`RequestResponseLogMiddleware` 记录耗时、usage、入站 header/body、出站 body（均脱敏）。`enabled=false` 不落盘。

## 二、核心数据契约：IREvent

所有上游事件先归一成 `IREvent`，三家 adapter 各自消费同一份 `IREvent` 流。这是整个框架的心脏，也是「换上游只改一处」的关键。

`app/events.py` 定义：

```python
class ToolEvent:
    name: str
    title: str = ""
    detail: dict = field(default_factory=dict)

class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cached_tokens: int = 0
    cache_creation_tokens: int = 0
    model: str | None = None
    provider: str | None = None

class IREvent:
    kind: Literal["text", "thinking", "tool", "finish", "error"]
    text: str = ""
    thinking: str = ""
    tool: ToolEvent | None = None
    usage_delta: Usage | None = None
    finish_reason: str | None = None
    error: str | None = None
```

**5 种 kind 的语义**：
- `text`：正文增量（assistant 回复内容）。
- `thinking`：思维链增量（reasoning）。adapter 必须按协议标准字段随响应返回（Chat `reasoning_content` / Responses `type=reasoning` / Anthropic `type=thinking`），流式随到随发，tool 路径不得丢弃。
- `tool`：工具调用事件（上游原生工具或 prompt 模式解析出的调用）。
- `finish`：本轮结束（带 `finish_reason`：`stop`/`length`/`tool_use`）。
- `error`：上游错误（透传给客户端，不重试）。

**契约稳定性**：IREvent 是稳定契约，勿轻改。新增需求优先扩 `ToolEvent.detail`，而非加 IREvent 字段。`tests/test_events.py` 锁定字段集合。

## 三、上游适配器 5 个角色（换目标网站时实现）

| 角色 | 文件 | 接口 | 改什么 |
|---|---|---|---|
| `AuthProvider` | `app/upstream/auth.py` | `get_auth() → dict[str,str]`、`is_auth_failure(exc)` | 认证链：cookie/JWT/OAuth refresh |
| `UpstreamClient` | `app/upstream/client.py` | `stream(prompt, model_id) → AsyncIterator[IREvent]`、`upload_image/upload_file` | 上游请求（URL/headers/body/流式协议）+ 多模态上传 |
| `EventParser` | `app/upstream/parser.py` | `parse(raw) → list[IREvent]` | **原生事件→IREvent，唯一核心改动** |
| `ModelRegistry` | `app/upstream/models.py` | `catalog()`/`normalize(model)`/`upstream_id_for(id)` | 模型目录（实地探测填入） |
| tool 策略 | settings `upstream_strategy` | `native`/`prompt` | 上游支持原生 function-calling 选 `native`，否则 `prompt` |

`UpstreamProvider`（`app/upstream/provider.py`）是组合器，把 Auth+Client 组成对外暴露的 duck-type 接口 `stream()`，供 `app/deps._RetryingClient` 与 `app/orchestrator` 使用。

## 四、数据流（一次请求）

```
客户端 POST /v1/chat/completions
  → verify_api_key (v1 key 校验，空则放行)
  → get_client (round-robin 取号 → _RetryingClient 包装)
  → adapter._build_prompt: extract_user_prompt(messages, model_id=)  # 拍平；无 system 时注入缺省身份
  → orchestrator.stream_with_retry(client, prompt, tools)
      ├─ build_tool_directive(tools)        # prompt 模式注入指令；native 不注入
      ├─ client.stream(prompt, model_id)     # 上游请求 → IREvent 流
      ├─ buffer 一轮 → parse_tool_calls
      └─ 若 refusal_detect：is_refusal → 换 retry 变体重试
  → adapter 把 IREvent 流转成各家格式（SSE 帧）
  → client._RetryingClient 捕获失效 → mark_failed → 503 → 客户端重试换号
```

## 五、可插拔接口（核心解耦点）

- **adapter 层**：`extract_user_prompt` 把 messages 拍平成单条 prompt（system **默认原样**；`soften_system=true` 时软化包装且不删改实质 + assistant 历史 tool_call 渲染成围栏 few-shot）；`flatten_text` 把 content block → 纯文本并**保留** thinking/reasoning。客户端 tools 定义完整进入 prompt/native 路径。
- **缺省身份 system**（`app/system_sanitizer.default_identity_system`）：当客户端**未**传任何非空 system / instructions 时，`extract_user_prompt(..., model_id=)` 前置注入一段短英文提示——声明对外 catalog model id，并禁止模型提及/暴露 webchat 平台名（`PLATFORM_NAME`，由 `copy_skeleton` 替换 `{{Platform}}`）。有客户端 system 时**不注入、不覆盖**。
- **对抗策略（默认关）**：`soften_system` / `refusal_detect` 仅在 `copy_skeleton --with-soften-system` / `--with-refusal-detect` 或 config 手动打开后生效。
- **orchestrator**：duck-type client，不依赖具体上游（`stream(prompt, model_id)`）。
- **deps**：`_RetryingClient` 捕获失效 → `classify_failure` → `FailReason` → `mark_failed`，换号对外透明。
- **换上游时只需改 `app/upstream/`**（其余 config/account/IREvent/orchestrator/adapters/admin/tools/tokens/streaming 不变）。
- **API 面**：启用的路由必须支持 stream + tools（见 `api-endpoints.md`）；初始化路由集由 `copy_skeleton` 开关决定。

## 六、参考实现

- 与上游无关的通用骨架见 `assets/skeleton/app/`（已写全可运行）。
- 上游适配器占位见 `assets/skeleton/app/upstream/`（接口+TODO）。
- PromptQL 上游完整实现见 `/data1/promptql2api/app/promptql/`（auth/client/events 三件套）。
