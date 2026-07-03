# {{Platform}}2api

> {{Platform}} 网页聊天（webchat）→ OpenAI / Anthropic 兼容本地 API 网关。
> "2api" = "to api"：把网页逆向成本地兼容 API。

把 {{Platform}} 的网页对话封装为标准 API，供任意支持 OpenAI / Anthropic 协议的客户端（ChatBox、Cursor、Claude Code、OpenAI SDK 等）接入。

## 特性

- **多协议兼容**：OpenAI `/v1/chat/completions`、`/v1/responses`、Anthropic `/v1/messages`、`/v1/models`
- **流式 + 非流式** + **tool call**（webchat 无原生 function-calling 时用 prompt 注入解析 + 真流式状态机）
- **多账户轮询** + 错误分类自动换号（认证失败 / 额度耗尽 / 人机验证）
- **token 用量**：上游真实 usage 优先，CJK 感知估算兜底
- **/admin 管理后台**（可选，独立鉴权）
- **注册机**（可选，配合临时邮箱 cf-temp-email 批量注册）

## 快速开始

```bash
# 1. 安装依赖（用 uv）
uv sync                # 主程序
uv sync --extra dev    # 含测试 / lint
uv sync --extra registrar  # 含注册机（curl-cffi / playwright）

# 2. 配置
cp config.toml.example config.toml   # 编辑：填上游端点、是否要 api_key/admin key
# 把账号凭据放到 account/main.json（见 account/main.json.example）

# 3. 运行
uv run uvicorn app.main:app --host 0.0.0.0 --port 8088
```

## 端点

| 端点 | 说明 |
|---|---|
| `POST /v1/chat/completions` | OpenAI Chat Completions（流式 + 非流式 + tool calls） |
| `POST /v1/responses` | OpenAI Responses（SSE typed events） |
| `POST /v1/messages` | Anthropic Messages（content blocks + tool_use） |
| `POST /v1/messages/count_tokens` | token 计数（估算） |
| `GET /v1/models` | 模型列表 |
| `/admin/*` | 账号管理（list / get / create / delete / reload，需 admin key） |
| `GET /healthz` | 健康检查 |

## 认证分层

- `/v1/*`：未设 `gateway.api_key` 则**无认证**；设了则需 `Authorization: Bearer <key>`。
- `/admin/*`：未设 `admin.auth_key` 则**整个 admin 关闭**（端点返回 404）；设了则需 Bearer 或 `?auth_key=`。

## 客户端示例

```bash
curl http://localhost:8088/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"你好"}],"stream":false}'
```

## 注册机（可选）

```bash
# 编辑 config.toml 的 [email] / [captcha] 段后：
uv run python -m registrar -n 3      # 注册 3 个账号，自动存入 account/
```

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
app/            # FastAPI 服务（config / account / IREvent / orchestrator / adapters / admin / upstream）
app/upstream/   # 上游适配器（换目标网站时只改这里）
registrar/      # 注册机（独立包）
tests/          # 单元测试
config.toml     # 配置（gitignore）
account/        # 账号凭据（gitignore）
```

## License

MIT

---

> 本项目使用 [2api-skill](https://github.com/69gg/2api-skill) 辅助制作。

