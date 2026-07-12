---
name: 2api-skill
description: >-
  Methodology skill that guides an agent to reverse-engineer a webchat site
  (chatgpt/grok/promptql-style 网页聊天) into a local OpenAI/Anthropic-compatible
  API gateway (a "2api" project, "to api" 的简写：FastAPI + uv, /v1 chat/responses/messages
  + /admin 账号池, optional 注册机). Use when the user wants to 逆向 webchat 为本地兼容 API、
  把网页对话做成 OpenAI 兼容接口、搭建 2api/to-api 网关、抓包网页聊天凭据、或为某平台写注册机。
license: MIT
---

# 2api-skill

把一个网页聊天（webchat，类似 chatgpt.com / grok.com / promptql 那种网页对话）**逆向成本地 OpenAI / Anthropic 兼容 API 服务**（俗称 "2api" = "to api"）。本 skill 是一份方法论：它带你走完「抓包识别凭据 → 生成 2api 服务（`/v1` + `/admin`）→ 可选写注册机」全流程，并附一套**通用 Python(FastAPI)+uv 骨架**（`assets/skeleton/`），换目标网站时只需改上游适配器。

> 本 skill 平台无关：适用于任何支持 skill 的 agent（Claude Code / OpenAI Codex / 其他）。文中 MCP 工具用全限定名引用，配置以 Claude Code 为示例，其他平台类比。

## 0. 何时使用 / 能力边界

**适用**：用户想把某 webchat 网页做成 OpenAI/Anthropic 兼容 API（"做个 xx2api"、"逆向 xx 网页为接口"）、抓取网页聊天凭据、或为某平台批量注册账号（写注册机）。

**局限（开工前如实告知用户）**：
- webchat 一般**不暴露原生 function-calling**：tool call 多靠 **prompt 注入 + 文本解析** 模拟（见 `references/tool-calls.md`），命中率取决于上游模型是否配合，复杂 system 身份场景可能识破失败。
  - **强 system / 身份对抗**：采用六层策略叠加命中率（见 `references/tool-calls.md` 第六章）。**不要承诺 100% tool call 命中**。
  - **但对外 API 面仍必须支持** `stream` 与 `tools`（见第 2 节第 7–8 条）；不得以上游无原生 FC 为由删掉兼容层。
- **人机验证（captcha/turnstile）**：能协议化最好；不能则需浏览器 + 打码或人工，**无法保证全自动**。是否启用打码**按实测**决定（见第 8–11 步）。
- **多模态（图片/文件）**：抓包若见上传接口则**必须**实现；若全程无上传接口，文档写明不支持即可。
- 本 skill 针对的是 **webchat 类**逆向（浏览器里能聊天的网页），不是有公开 SDK 的官方 API。

## 1. 前置：工具能力检查（每次开工先做）

本流程依赖两组工具，**开工前先浏览你当前可用的工具列表**，确认以下能力是否存在：

- **context7 / 文档查询**（查上游/库文档与正确用法）：例如 `context7:resolve-library-id`、`context7:query-docs` 或类似名称。若不可用，可降级为 `WebSearch` / `FetchURL`。
- **chrome-devtools / 浏览器 DevTools**（连真实浏览器抓包、探测模型列表）：例如 `chrome-devtools:navigate_page`、`list_network_requests`、`get_network_request`、`evaluate_script`、`click_element`、`take_snapshot` 或类似名称。若不可用，可降级为让用户在浏览器 DevTools 手动抓 Network，把请求 JSON 喂给 `scripts/request_to_curl.py` 转 curl。

> 不同 agent 对工具命名/前缀不同，以你实际枚举到的为准；下文中统一用 `context7:*` 和 `chrome-devtools:*` 作为示意。

**若任一缺失或不全**（这是常态，容错处理）：
1. **教用户配 MCP**（若你所在平台支持）：在目标项目根写 `.mcp.json`（团队共享）或用户级 `~/.claude.json` 的 `mcpServers`，内容：
   ```json
   {
     "mcpServers": {
       "context7": { "command": "npx", "args": ["-y", "@upstash/context7-mcp"] },
       "chrome-devtools": { "command": "npx", "args": ["-y", "chrome-devtools-mcp@latest", "--autoConnect"] }
     }
   }
   ```
   写完**明确提示用户：需重启 agent（如 Claude Code）才生效**。其他 agent 平台参考各自 MCP 配置文档。
2. **降级继续**：文档查询不可用 → 用 `WebSearch` / `FetchURL` 查文档；浏览器 DevTools 不可用 → 让用户在浏览器 DevTools 手动抓 Network，把请求 JSON 喂给 `scripts/request_to_curl.py` 转 curl。
3. **权限反复弹**：提示用户把 `mcp__chrome-devtools__*`、`mcp__context7__*` 加入项目的 `.claude/settings.local.json` 的 `permissions.allow`。

## 2. 强制约定（必须执行，详见 `references/project-conventions.md`）

1. **项目命名**：用户无特别要求时，生成的项目命名为 **`<平台>2api`**（如 `grok2api`、`promptql2api`）；用户指定则从其指定。
2. **必须用 `copy_skeleton.py` 初始化**：**禁止**手写骨架或从别处抄项目。根据第 0 步需求与第 2–3 步抓包结论传入功能开关（路由 / 注册机 / 邮件 OTP / captcha / `--init-git`）。详见第 4 步与 `references/project-conventions.md`。
3. **README 致谢**：生成的项目 `README.md` **末尾**必须包含：
   `> 本项目使用 [2api-skill](https://github.com/69gg/2api-skill) 辅助制作。`
   README 只写用户运维向内容，**不要**塞 IREvent、状态机、三级解析等内部设计话术。
4. **git 忽略**：`config.toml` 忽略；`config.toml.example` **不**忽略；`account/`（或 `accounts/`）忽略但保留 `*.example`；**必须**含 `__pycache__/`、`*.pyc`、`.venv/`、`.env`、`.pytest_cache/` 等。`copy_skeleton` / `git_init.sh` 会「缺则追加」，agent 不得删掉 `__pycache__/` 行。
5. **认证分层**：`/v1/*` 不设 `gateway.api_key` 则**无认证**；`/admin/*` 不设 `admin.auth_key` 则**整个 admin 关闭**（404）。二者独立。
6. **license MIT**：生成的项目与配置都用 MIT。
7. **诚实**：token 用量、能力边界如实说明，无真实值则估算并标注，绝不编造。
8. **API 面：流式 + tool calls（强制）**：启用的 `/v1` 路由必须支持 `stream=true/false`，并接受 `tools`、按协议返回 `tool_calls` / `tool_use` / function_call 帧。上游无原生 FC 时用 prompt 注入实现，**不得删除兼容层**；命中率不承诺 100%。真流式或伪流式（切片 SSE）均可，客户端须见标准 SSE。
9. **system / tools 实质内容不删改**：客户端 → 上游上下文组装时，system/instructions 与 tools 的**实质指令与 schema 不得删改**。允许：`soften_system` 外层包装、删除纯垃圾元数据行、协议字段名映射、prompt 模式**前置追加** directive（tools 定义须完整写入）、**仅当客户端未传非空 system 时**注入缺省身份提示（声明对外 model id + 禁止提及 webchat 平台，见 `default_identity_system`）。禁止：改写/覆盖已有客户端身份或规则、阉割 parameters、丢弃 tools 列表。
10. **reasoning 透传（强制）**：客户端 history 中的 `reasoning_content` / `thinking` / `reasoning` 等不得丢弃；上游若产思维链，parser 必须发 `IREvent(kind="thinking")`，adapter **随响应按各协议标准格式返回**（Chat: `reasoning_content`；Responses: `type=reasoning`；Anthropic: `type=thinking` / `thinking_delta`）。流式随到随发，tool 路径不得丢弃。
11. **文件上传（条件强制）**：抓包发现 upload / attachment / presigned / base64 文件字段 → **必须**实现 `upload_image`/`upload_file`（或等价）并在对话请求中引用；全程无上传接口 → 文档写明不支持即可。

## 3. 工作流总览

| 步 | 动作 | 关键资产 |
|---|---|---|
| 0 | 询问需求、说明局限 | — |
| 1 | 用户先建一个目标渠道账号 | — |
| 2 | chrome-devtools 连账号发对话、抓请求 | `references/capture-flow.md`、`scripts/request_to_curl.py` |
| 3 | 识别凭据、本地 curl 验证、记录凭据 | `references/capture-flow.md` |
| 4 | 询问是否用 git；用 copy_skeleton（含功能开关）初始化 | `scripts/copy_skeleton.py`、`scripts/git_init.sh`、`references/project-conventions.md` |
| 5 | 编写 2api 代码（a 框架 / b /v1 / c /admin / d 认证 / e 文档测试 / f lint / g 提交） | `references/architecture.md` 起、`scripts/probe_catalog.py` |
| 6 | 用真实账号测试（对话/stream/tool/多模态），修错 | `scripts/e2e_smoke.py` |
| 7 | 询问是否写注册机（否→结束） | — |
| 8–11 | 写注册机（按实测启用 email-otp / captcha；写码 / 存账号 / 文档测试） | `references/registrar-protocol.md` |
| 12 | 询问是否测试运行；修错；commit | `scripts/e2e_smoke.py` |

## 4. 第 0–3 步：需求与抓包

**第 0 步**：问清目标 webchat 的 URL、想要的端点（OpenAI Chat / Responses / Anthropic Messages / admin）、是否多账户、是否需要注册机、**是否用 git**。同步说明第 0 节的局限。端点与 git 答案将映射为 `copy_skeleton` 开关。

**第 1 步**：让用户**手动**在目标网站注册一个账号并登录（除非已有）。

**第 2 步（抓包）**：用 `chrome-devtools` 连到用户已登录的浏览器 → `navigate_page` 到 webchat → `list_network_requests`（过滤 XHR/fetch）→ 在网页发一条对话 → 用 `get_network_request` 取关键的「发送消息」请求（通常是 POST，返回 SSE/JSON 流）→ 必要时 `evaluate_script` 取 `localStorage`/cookie/页面变量里的 token。若站点支持发图/文件，再抓一次上传相关请求。详见 `references/capture-flow.md`。

**第 3 步（验证凭据）—— 阻塞项**：把抓到的请求喂 `scripts/request_to_curl.py` 转成 curl，**本地用 curl 实跑验证**能拿到回复。识别凭据类型（cookie / JWT / Bearer / 会话 ID / 签名头）。成功后把凭据记到 `account/main.json`（字段由上游决定）。

> **未通过 curl 本地验证的凭据，不要进入第 5 步写代码，更不要开注册机批量注册。** 只有单个账号能稳定拿到回复，才能确认凭据字段、协议、token 生命周期正确。
>
> 选择凭据时**优先长期有效**的：refresh_token、长效 cookie、service account key 等。若只能拿到短时效 token，必须在 `app/upstream/auth.py` 实现自动刷新，并用 `app/upstream/token_store.py` 的文件锁持久化。
>
> 抓包理解上游协议时，优先用 `context7` 查上游相关库/协议文档确认正确用法，再下结论。

## 5. 第 4 步：git 与项目初始化

1. **目录策略由 AI 自动选择（默认直接复制）**：
   - 若目标目录为空（`.git` 除外），直接复制骨架到该目录。
   - 若目标目录非空，自动在其下新建 `<平台>2api` 子目录，复制到子目录。
   - 若目标目录及其 `<平台>2api` 子目录均非空，**告知用户选择一个新目录**，不要擅自覆盖。
2. **必须**调用 skill 自带的 `scripts/copy_skeleton.py`（禁止手写/外拷骨架）。根据第 0 步与抓包结论传开关，例如：
   ```bash
   # 用户要 git + 只要 chat/admin，暂不要注册机
   python /path/to/2api-skill/scripts/copy_skeleton.py --platform <平台> --dest <目录> \
     --init-git --no-responses --no-messages --with-admin

   # 用户不要 git，三套协议全开
   python /path/to/2api-skill/scripts/copy_skeleton.py --platform <平台> --dest <目录> --no-init-git
   ```
   **开关一览**（详见 `references/project-conventions.md`）：
   - 路由（默认全开）：`--with-chat/--no-chat`、`--with-responses/--no-responses`、`--with-messages/--no-messages`、`--with-admin/--no-admin`（`/v1/models` 与 `/healthz` 始终保留）
   - 注册机（默认关）：`--with-registrar`、`--with-email-otp`、`--with-captcha`（后两者隐含 registrar）
   - git（默认关）：`--init-git` / `--no-init-git`、可选 `--git-remote <url>`
3. 脚本会：复制骨架 → 按开关裁剪路由/文档/配置 → 确保 `.gitignore` 含 `__pycache__/` → 写入 `.2api-skill-features.json` → 若 `--init-git` 则调用 `git_init.sh`。
4. 若第 0 步用户要 git 但漏了 `--init-git`，可补跑：`bash scripts/git_init.sh --dir <项目> [--remote <url>]`（或位置参数 `bash scripts/git_init.sh <项目> [remote]`）。`git_init` 对标准忽略做「缺则追加」。
5. 复制后即可 `uv sync`（上游适配器仍是占位，需第 5 步填充）。注册机相关开关可在第 7 步后再补目录/配置，但**首次初始化仍必须走 copy_skeleton**。

## 6. 第 5 步：编写 2api 代码（分小步，边写边测）

骨架已把**与上游无关的部分写全**（config / 账号池 / IREvent / orchestrator / 已启用的 adapter / tools / tokens / streaming / admin），你只需填 **`app/upstream/`** + 配置 + 模型列表。先读 `references/architecture.md` 理解分层与 IREvent 契约。

- **a 框架**：确认 `config.toml`（从 `config.toml.example` 复制并填值）、账号池轮询、请求抽象就位。→ `references/architecture.md`、`upstream-adapters.md`
- **b `/v1`（已启用的路由）**：
  - 模型列表**实地探测，绝不硬编码**——用 `chrome-devtools` + `scripts/probe_catalog.py` 生成 `MODEL_CATALOG`。
  - **流式 / 非流式 API 面必须可用**（`references/streaming.md`）。
  - **tools API 面必须可用**（`references/tool-calls.md`：native 或 prompt）。
  - token 用量（`references/tokens-usage.md`）。
  - **system/tools 实质不删改**（第 2 节第 9 条）；**reasoning 透传**（第 2 节第 10 条）。
  - **上传**：抓包有接口则必须实现（第 2 节第 11 条；`references/upstream-adapters.md`）。
  - → `references/api-endpoints.md`
- **c `/admin`**：若初始化时启用了 admin，管理凭据（列/增/删/启停、reload）。骨架已给 5 端点。
- **d 认证**：`/v1` 与 `/admin` 分开（约定第 5 条）。**务必确认每个 `/v1` 端点真挂了 `verify_api_key`**（骨架已挂，勿拆）。→ `references/auth-and-errors.md`
- **e 文档 + 测试**：在骨架 README 上补上游特有信息（模型名、限制），保持用户向；按 `references/testing.md` 补单测。
- **f lint + 单测**：`uv run ruff check . && uv run pytest`，修到全绿。
- **g 提交**：若启用了 git，约定式提交（`feat:`/`fix:`/`docs:`/`test:`/`refactor:`）。

> 每完成一个端点，立即用 `scripts/e2e_smoke.py` 冒烟，不要堆到最后。

## 7. 第 6 步：真实账号测试

用第 3 步记录的真实账号凭据，跑各类场景：普通对话、流式、tool call（单轮/多轮）、多模态（若支持）。`scripts/e2e_smoke.py --suite chat,stream,tool`。修复发现的问题；有 git 则提交。

## 8. 第 7 步：询问是否写注册机

告知用户「2api 服务段落告一段落」。**询问是否需要注册机**：
- **不需要** → 收尾（确认文档/测试/提交），结束。
- **需要** → 先确认单个账号已通过 curl 验证并能稳定请求；否则退回第 3 步，不要直接批量注册。
- 若首次 `copy_skeleton` 未带 `--with-registrar`，此时再复制/补齐 `registrar/` 相关文件与配置，或在空目录用正确开关重建（**勿覆盖已有工作**时改为手工从骨架拷 `registrar/` 并改 config）。
- 进入第 8–11 步。

## 9. 第 8–11 步：注册机

> 详见 `references/registrar-protocol.md`。能力按**实测**启用，禁止未观察就默认全开 email-otp / captcha。

- **第 8 步（邮件能力）**：用隔离 profile 预判注册是否需要**邮件验证码**：
  - **需要 OTP** → 向用户要 cf-temp-email 凭据，写入 `[email]`；`copy_skeleton` 应带 `--with-email-otp`。
  - **只需邮箱字段、无验证码** → **不**启用收件/轮询；随便编合规邮箱即可；`PROTOCOL.md` 第四节填 `N/A`。
- **第 9 步**：用**隔离 profile 的浏览器**走一遍注册流程，观察每个请求。**若无邮箱注册入口**（仅 OAuth/手机号），如实告知用户暂时无法实现并停下。需要 OTP 时邮件用 curl（cf-temp-email API）取，并确定验证码正则。请求序列与凭据获取方式记入 `registrar/PROTOCOL.md`（节号固定，未启用能力写 `N/A`，不要删节）。
- **第 10 步**：检查是否有人机验证：
  - **无** → 纯协议注册；不启用 `[captcha]`（`--no-captcha`）；PROTOCOL 第二节写无 captcha。
  - **有** → 配置 `[captcha]`，走 semi / cdp / api 之一（`--with-captcha`）。
- **第 11 步**：编写注册机代码（`registrar/`：填 pipeline；按需填 captcha / email_client 调用）。注册成功账号**自动保存到 `account/`**。若需运行时维持池数量，设 `[registry] target_account_count > 0`。补文档与测试。

## 10. 第 12 步：测试运行与收尾

询问用户是否需要**实际跑一次注册机**测试：
- 需要 → 运行，修复错误，确认账号成功写入 `account/`。
- 不需要 → 跳过。

若启用了 `target_account_count`，启动网关后观察日志是否自动补足账号到目标数。

最后：确认 `README`（含致谢、用户向措辞）、测试、lint 全绿，`.gitignore` 含 `__pycache__/`；有 git 则最终 commit（约定式）。

## 11. 速查：换上游只改哪里

生成新 2api 时，**唯一必改的是 `app/upstream/`**（上游适配器）：

| 文件 | 改什么 |
|---|---|
| `upstream/auth.py` | 认证链（cookie/JWT/OAuth 刷新），`get_auth()` 返回请求头，`is_auth_failure()` 判定失效 |
| `upstream/client.py` | 上游请求（URL/headers/body/流式协议 SSE·JSON Lines·轮询），`stream() → IREvent`；有上传则实现 upload_* |
| `upstream/parser.py` | **原生事件 → IREvent**（含 thinking/reasoning → `kind="thinking"`） |
| `upstream/models.py` | `MODEL_CATALOG`（用 `probe_catalog.py` 探测填入） |
| `upstream/account_fields.py` | 上游专属凭据字段 |
| `upstream/__init__.py` | `ToolCallStrategy` 选 native/prompt |

其余（config/account/IREvent/orchestrator/adapters/admin/tools/tokens/streaming）保持不变。详见 `references/upstream-adapters.md`。

## 参考资料索引（按需阅读，不要一次全读）

- `references/architecture.md` — 通用架构蓝图 + IREvent 契约 + 5 个上游适配器接口
- `references/api-endpoints.md` — `/v1` + `/admin` 端点规范（stream/tools API 面必须）
- `references/tool-calls.md` — tool 双模 + 解析 + system/tools 实质不删改
- `references/streaming.md` — SSE；真/伪流式均为合法实现
- `references/tokens-usage.md` — 真实优先 + CJK 估算 + 三家 usage 映射
- `references/upstream-adapters.md` — 换网站只改 `app/upstream/` + 上传条件强制 + 模型探测
- `references/auth-and-errors.md` — 认证分层 + 错误分类换号
- `references/capture-flow.md` — chrome-devtools 抓包 + curl 验证 + 凭据识别
- `references/registrar-protocol.md` — 按实测启用 email-otp / captcha
- `references/project-conventions.md` — 命名 / copy_skeleton 开关 / gitignore / 约定式提交
- `references/testing.md` — mock client + e2e
- `references/supabase-auth.md` — Supabase Auth 套路
- `scripts/` — `copy_skeleton.py`、`request_to_curl.py`、`probe_catalog.py`、`e2e_smoke.py`、`git_init.sh`
- `assets/skeleton/` — 通用 Python(FastAPI)+uv 骨架
