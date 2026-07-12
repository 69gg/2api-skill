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

> **凭据生命周期优先**：抓包时尽量选择长期有效的凭据（refresh_token、长效 cookie、service account key）。若只能拿到短时效 token，必须在 `app/upstream/auth.py` 实现自动刷新，并用 `app/upstream/token_store.py` 的文件锁持久化，避免多 worker 刷新覆盖。

- **纯 cookie 回放**：`get_auth()` 返回 `{"Cookie": "..."}`；适合无 token 刷新的简单站点。
- **JWT + 刷新**：缓存 token，到期前 `token_refresh_margin` 秒主动刷新；参考 promptql2api 的 `AuthManager`（`asyncio.Lock` 双重检查锁 + base64 解析 JWT exp）。刷新后必须写回持久化（账号 json 或 `token_store`）。
- **OAuth refresh**：用 `refresh_token` 换 `access_token`；适合需要 OAuth 流程的站点（如 ChatGPT 系、Supabase Auth）。

```python
# JWT + 刷新伪代码（get_auth 内）
async def get_auth(self) -> dict[str, str]:
    exp = _jwt_exp(self._account.access_token)
    if exp - time.time() < self._settings.token_refresh_margin:
        new_session = locked_refresh(
            TOKEN_PATH,
            lambda old: self._refresh(old["refresh_token"]),
        )
        self._account.access_token = new_session["access_token"]
        # 可选写回 account/<name>.json
    return {"Authorization": f"Bearer {self._account.access_token}"}
```

`is_auth_failure` 默认按 HTTP 401/403 判定；`AuthProvider.classify_failure` 可按目标站覆盖，处理额度耗尽、Pro 模型错误、visitor_id 校验失败等特殊状态码/ body。

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

**条件强制**（SKILL.md 第 2 节第 11 条）：

| 抓包结果 | 要求 |
|---|---|
| 发现 upload / attachment / presigned / base64 文件字段 | **必须**实现 `upload_image` / `upload_file`（或等价），并在对话请求体中引用返回的 id/url |
| 全程无上传相关接口 | 文档写明「本上游不支持多模态上传」；可保留 stub 返回明确错误 |

| 范式 | 说明 | 适用 |
|---|---|---|
| **JSON + base64 单步** | 文件内容 base64 后塞进请求体 JSON 字段，一次 POST 上传拿引用 id；轻量、无 multipart | 小文件/图片，如 grok.com |
| **对象存储 presigned 三步** | ① POST 拿 presigned upload_url + file_id → ② PUT 到对象存储（如 Azure Blob）→ ③ POST 确认上传完成；返回 file_id 供后续对话引用 | ChatGPT 系 |

`upload_image`/`upload_file` 返回上游引用（url/id），在 `stream()` 的请求体里引用它（如 `fileAttachments`/`attachment`）。详见 `references/capture-flow.md`。

## 五、模型探测（勿硬编码）

`app/upstream/models.py` 的 `MODEL_CATALOG` 必须实地探测后填入：

1. 用 chrome-devtools 抓取上游的模型列表来源：
   - 优先找 `/models` API 或动态模型接口；
   - 若无，从网页模型选择器 UI 按钮 `data-testid`/`data-*` 属性提取；
   - 若模型写死在前端 JS bundle，抓 bundle 文件。
2. 喂给 `scripts/probe_catalog.py` 生成 `MODEL_CATALOG` 代码（含 `id/name/owner/upstream_id`），粘进 `app/upstream/models.py` 替换占位。支持三种来源：
   ```bash
   python scripts/probe_catalog.py --source models.json
   python scripts/probe_catalog.py --source https://api.example.com/v1/models --source-type api
   python scripts/probe_catalog.py --source dist/main.js --source-type bundle
   ```
3. `upstream_id_for` 把 catalog id 映射成上游真实模型标识（如 `llm_config_id`/上游 model name），供 `stream()` 用。

## 六、ToolCallStrategy 选型

- 上游支持原生 function-calling → `settings.upstream_strategy = "native"`，client 直接产 `IREvent(kind="tool")`。
- 上游不支持 → `settings.upstream_strategy = "prompt"`，靠 prompt 注入解析（见 `references/tool-calls.md`）。
- 无论哪种：**对外 API 面**仍须接受 `tools` 并返回标准 tool 帧。

## 七、reasoning / thinking 事件

- **入站**：history 中的 `reasoning_content`、Anthropic `thinking` block、Responses `reasoning` block 等，经 `extract_user_prompt` / `flatten_text` 进入上游上下文，**不得丢弃**。
- **出站**：上游 SSE/事件若含思维链，`parser.py` **必须**产出 `IREvent(kind="thinking")`，由 adapter 映射到各协议字段；禁止只解析 text。

## 八、错误分类换号（见 `references/auth-and-errors.md`）

`app/deps.py:classify_failure` 把上游异常映射成 `FailReason`。按目标站定制 body 关键词列表（`_AUTH_HINTS`/`_BAN_HINTS`/`_QUOTA_HINTS`/`_CF_HINTS`），避免误判。

## 九、参考实现

- PromptQL 上游完整实现：`/data1/promptql2api/app/promptql/`（auth.py/client.py/events.py 三件套）。
- grok2api/gpt2api/cursor2api 上游适配：见各项目源码（不同协议/认证/上传范式）。
