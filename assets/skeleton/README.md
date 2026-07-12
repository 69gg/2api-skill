# {{Platform}}2api

> {{Platform}} 网页聊天（webchat）→ OpenAI / Anthropic 兼容本地 API 网关。
> "2api" = "to api"：把网页逆向成本地兼容 API。

把 {{Platform}} 的网页对话封装为标准 API，供任意支持 OpenAI / Anthropic 协议的客户端（ChatBox、Cursor、Claude Code、OpenAI SDK 等）接入。

## 特性

- **多协议兼容**：OpenAI / Anthropic 风格端点（见下方端点表）
- **流式与非流式**，以及 **tool calls**（兼容常见客户端协议）
- **多账户轮询**与失败自动换号
- **token 用量**：优先返回上游真实 usage，否则估算
- **缺省身份**：请求未带 system / instructions 时，自动注入「真实 model id + 勿提及平台」提示
<!-- FEATURE:admin -->
- **/admin 管理后台**（可选，独立鉴权）
<!-- /FEATURE:admin -->
<!-- FEATURE:registrar -->
- **注册机**（可选，批量注册账号写入 `account/`）
<!-- /FEATURE:registrar -->

## 快速开始

```bash
# 1. 安装依赖（用 uv）
uv sync                # 主程序
uv sync --extra dev    # 含测试 / lint
<!-- FEATURE:registrar -->
uv sync --extra registrar  # 含注册机依赖
<!-- /FEATURE:registrar -->

# 2. 配置
cp config.toml.example config.toml   # 编辑：填上游端点、是否要 api_key/admin key、可选 [proxy]
cp account/main.json.example account/main.json   # 必填字段：name、source_email、created_at

# 3. 运行
uv run uvicorn app.main:app --host 0.0.0.0 --port 8088
```

## 端点

| 端点 | 说明 |
|---|---|
<!-- FEATURE:chat -->
| `POST /v1/chat/completions` | OpenAI Chat Completions（流式 + 非流式 + tool calls） |
<!-- /FEATURE:chat -->
<!-- FEATURE:responses -->
| `POST /v1/responses` | OpenAI Responses |
<!-- /FEATURE:responses -->
<!-- FEATURE:messages -->
| `POST /v1/messages` | Anthropic Messages |
| `POST /v1/messages/count_tokens` | token 计数（估算） |
<!-- /FEATURE:messages -->
| `GET /v1/models` | 模型列表 |
<!-- FEATURE:admin -->
| `/admin/*` | 账号管理（list / get / create / delete / reload，需 admin key） |
<!-- /FEATURE:admin -->
| `GET /healthz` | 健康检查 |

## 认证分层

- `/v1/*`：未设 `gateway.api_key` 则**无认证**；设了则需 `Authorization: Bearer <key>`。
<!-- FEATURE:admin -->
- `/admin/*`：未设 `admin.auth_key` 则**整个 admin 关闭**（端点返回 404）；设了则需 Bearer 或 `?auth_key=`。
<!-- /FEATURE:admin -->

## 代理

在 `config.toml` 的 `[proxy]` 段配置（皆可留空 = 直连）：

| 键 | 用途 | 回退 |
|---|---|---|
| `url` | 网关访问上游 | 空 → 直连 |
| `registrar_url` | 注册机 HTTP / 自动补号 / captcha | 空 → `url` → 直连 |

CLI 注册时还可用 `--proxy` 临时覆盖配置中的注册机代理。

## 客户端示例

```bash
curl http://localhost:8088/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"你好"}],"stream":false}'
```

<!-- FEATURE:registrar -->
## 注册机（可选）

```bash
# 按实测编辑 config.toml 中与注册相关的段后：
uv run python -m registrar -n 3      # 注册 3 个账号，自动存入 account/
```
<!-- /FEATURE:registrar -->

## 测试

```bash
uv run pytest        # 单元测试（mock 上游，不依赖真实网站）
uv run ruff check .  # lint
```

## Docker

```bash
docker compose up -d   # 用 docker-compose.yml，config.toml 与 account/ 通过 volume 挂载
```

## 目录结构

```
app/            # FastAPI 服务
app/upstream/   # 上游适配器（换目标网站时只改这里）
<!-- FEATURE:registrar -->
registrar/      # 注册机（独立包）
<!-- /FEATURE:registrar -->
tests/          # 单元测试
config.toml     # 配置（gitignore）
account/        # 账号凭据（gitignore）
```

## License

MIT

---

> 本项目使用 [2api-skill](https://github.com/69gg/2api-skill) 辅助制作。
