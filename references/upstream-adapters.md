# 上游适配器（换目标网站时只改 `app/upstream/`）

> 详见 `references/architecture.md` 的 5 个角色。本节给出每个文件的实现要点与常见范式。

## 一、文件清单与职责

| 文件 | 改什么 |
|---|---|
| `app/upstream/auth.py` | `AuthProvider.get_auth()` 返回请求头/cookie；`is_auth_failure(exc)` 判定账号失效 |
| `app/upstream/client.py` | `UpstreamClient.stream(prompt, model_id)` 构造上游请求 → 解析响应 → 产 IREvent 流；`upload_image/upload_file` 多模态上传 |
| `app/upstream/parser.py` | `EventParser.parse(raw)` **原生事件→IREvent**（换上游唯一核心改动） |
| `app/upstream/models.py` | `MODEL_CATALOG` 模型目录（**实地探测填入，勿硬编码**）+ `ModelRegistry.normalize/upstream_id_for` |
| `app/upstream/account_fields.py` | 上游账号专属凭据字段说明（`UPSTREAM_ACCOUNT_FIELDS`） |
| `app/upstream/__init__.py` | `get_provider()` 组合 provider（一般无需改） |

## 二、认证范式（按目标站选其一）

- **纯 cookie 回放**：`get_auth()` 返回 `{"Cookie": "..."}`；适合无 token 刷新的简单站点。
- **JWT + 刷新**：缓存 token，到期前 `token_refresh_margin` 秒主动刷新；参考 promptql2api 的 `AuthManager`（`asyncio.Lock` 双重检查锁 + base64 解析 JWT exp）。
- **OAuth refresh**：用 `refresh_token` 换 `access_token`；适合需要 OAuth 流程的站点（如 ChatGPT 系）。

`is_auth_failure` 默认按 HTTP 401/403 判定；可在 `app/deps.py:classify_failure` 按目标站补充 body 关键词（如 `EnrichToken`/`auth token` 字样）。

## 三、上游请求与流式协议

`app/upstream/client.py` 的 `stream()` 是核心。先确认上游协议家族：

| 协议 | 实现 |
|---|---|
| **SSE**（`text/event-stream`） | httpx `client.stream()` 逐行读 `data: {...}`，每行喂 `parser.parse()`；逐 token 真流式 |
| **JSON Lines**（NDJSON） | 逐行读 JSON 喂 `parser.parse()` |
| **轮询**（GraphQL subscription 等） | `start_thread` → `while True: query_events(after_id)` → 解析 → `await asyncio.sleep(poll_interval)`，到 `finish` 即止；伪流式整块返回（参考 promptql2api） |
| **单次 POST**（整块返回） | 直接解析响应体 → `parser.parse()` |

请求头：注入 `await self._auth.get_auth()` 返回的 headers；带 origin/referer/UA 等（参考 promptql2api/cursor2api 的指纹模拟）。

## 四、多模态上传（两种范式）

| 范式 | 说明 | 适用 |
|---|---|---|
| **JSON + base64 单步** | 文件内容 base64 后塞进请求体 JSON 字段，一次 POST 上传拿引用 id；轻量、无 multipart | 小文件/图片，如 grok.com |
| **对象存储 presigned 三步** | ① POST 拿 presigned upload_url + file_id → ② PUT 到对象存储（如 Azure Blob）→ ③ POST 确认上传完成；返回 file_id 供后续对话引用 | ChatGPT 系 |

`upload_image`/`upload_file` 返回上游引用（url/id），在 `stream()` 的请求体里引用它（如 `fileAttachments`/`attachment`）。详见 `references/capture-flow.md` 抓包确认上传方式。

## 五、模型探测（勿硬编码）

`app/upstream/models.py` 的 `MODEL_CATALOG` 必须实地探测后填入：

1. 用 chrome-devtools 抓取上游的模型列表来源（如有 `/models` API 取响应；否则从网页的模型选择器 UI 按钮 `data-testid`/`data-*` 属性提取）。
2. 喂给 `scripts/probe_catalog.py` 生成 `MODEL_CATALOG` 代码（含 `id/name/owner/upstream_id`），粘进 `app/upstream/models.py` 替换占位。
3. `upstream_id_for` 把 catalog id 映射成上游真实模型标识（如 `llm_config_id`/上游 model name），供 `stream()` 用。

## 六、ToolCallStrategy 选型

- 上游支持原生 function-calling → `settings.upstream_strategy = "native"`，client 直接产 `IREvent(kind="tool")`。
- 上游不支持 → `settings.upstream_strategy = "prompt"`，靠 prompt 注入解析（见 `references/tool-calls.md`）。

## 七、错误分类换号（见 `references/auth-and-errors.md`）

`app/deps.py:classify_failure` 把上游异常映射成 `FailReason`。按目标站定制 body 关键词列表（`_AUTH_HINTS`/`_BAN_HINTS`/`_QUOTA_HINTS`/`_CF_HINTS`），避免误判。

## 八、参考实现

- PromptQL 上游完整实现：`/data1/promptql2api/app/promptql/`（auth.py/client.py/events.py 三件套）。
- grok2api/gpt2api/cursor2api 上游适配：见各项目源码（不同协议/认证/上传范式）。
