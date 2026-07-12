# 2api-skill

> 把一个**网页聊天（webchat）**逆向成本地 **OpenAI / Anthropic 兼容 API 服务**——即 "2api"（"to api" 的简写）。

这是一个 **agent skill（方法论 + 可复用骨架）**：当用户想把某个网页对话（类似 chatgpt.com / grok.com / promptql 那种）做成 OpenAI/Anthropic 兼容接口时，引导 agent 走完整流程——**抓包识别凭据 → 生成 2api 服务（`/v1` + `/admin`）→ 可选写注册机**，并附一套通用 Python(FastAPI)+uv 骨架，换目标网站时只改上游适配器。

## 它解决什么问题

很多优秀的 AI 能力只藏在网页背后（没有公开 API，或有但限制多）。本 skill 把"逆向网页聊天为标准兼容 API"这套重复工程**模板化**：账号池轮询、流式、tool call、token 用量、admin 管理、注册机——通用的部分一次写好，每次只填与具体网站耦合的那一小块。

## 适用场景

- "帮我把 xx 网页做成 OpenAI 兼容 API"（做个 `xx2api`）
- 抓取某网页聊天的请求凭据（cookie/JWT/token）
- 为某平台批量注册账号（写注册机，配合临时邮箱）

**局限**：针对 webchat 类逆向；tool call 多靠 prompt 模拟（命中率依上游）；人机验证不一定能全自动；多模态依上游支持情况。详见 `SKILL.md` 第 0 节。

## 安装（多平台）

本 skill 不绑定单一 agent 平台。

**Claude Code**（开发期热更新，推荐）：

```bash
git clone https://github.com/69gg/2api-skill.git ~/projects/2api-skill
ln -s ~/projects/2api-skill ~/.claude/skills/2api-skill
# 重启 Claude Code 后即可自动发现
```

**OpenAI Codex / 其他支持 skill 的 agent**：通过本仓库的 `agents/openai.yaml` 接口识别；按各平台文档放置 skill 目录即可。

## 依赖的工具

流程依赖两组工具，agent 开工前应先浏览自身可用工具列表确认：

| 工具组 | 用途 | 缺失时替代 |
|---|---|---|
| `context7:*` 或类似文档查询工具 | 查上游/库文档与正确用法 | `WebSearch` / `FetchURL` |
| `chrome-devtools:*` 或类似浏览器 DevTools 工具 | 连真实浏览器抓包、探测模型 | 让用户在浏览器 DevTools 手动抓 Network |

需要时可在对应平台配置 MCP server（`context7`、`chrome-devtools`），配置后需重启 agent。详见 `SKILL.md` 第 1 节。

## 用法

安装后，在 agent 会话里用自然语言触发即可（也可显式 `/2api-skill`）：

> "帮我把 https://xxx.com 这个网页聊天逆向成本地 OpenAI 兼容 API"

agent 会按 `SKILL.md` 的 0–12 步工作流执行：询问需求 → 抓包 → curl 验证 → **用 `scripts/copy_skeleton.py`（功能开关：路由 / 注册机 / email-otp / captcha / `--init-git`）初始化** → 编写 `/v1`+`/admin` → 测试 → 询问是否写注册机 → （按实测启用 OTP/打码）→ 收尾。

## 目录结构

```
2api-skill/
├── SKILL.md                 # 主工作流（正文中文，≤500 行）
├── agents/openai.yaml       # Codex 等跨平台兼容入口
├── references/              # 11 篇方法论文档（按需阅读）
├── scripts/                 # 辅助脚本（copy_skeleton / request_to_curl / probe_catalog / e2e_smoke / git_init）
└── assets/skeleton/         # 通用 Python(FastAPI)+uv 骨架（app/ 写全 + app/upstream/ 占位 + registrar/ + tests/）
```

## 生成的项目约定

本 skill 生成的 2api 项目遵循：

- **命名**：默认 `<平台>2api`（如 `grok2api`、`promptql2api`）。
- **初始化**：必须用 `scripts/copy_skeleton.py`，禁止手写骨架；开关覆盖路由、注册机能力、是否 `--init-git`。
- **README 致谢**：项目 README 末尾含 `> 本项目使用 [2api-skill](https://github.com/69gg/2api-skill) 辅助制作`；README 保持用户运维向。
- **API 面**：启用的 `/v1` 路由支持流式/非流式与 tool calls；system/tools 实质不删改；reasoning 透传；有上传接口则实现上传。
- **认证分层**：`/v1` 不设 key 则无认证；`/admin` 不设 key 则整个 admin 关闭（404）。
- **git 忽略**：`config.toml` 与 `account/`（凭据）忽略，`config.toml.example` 与 `*.example` 入库；**必须含 `__pycache__/`**。
- **license**：MIT。

## 参考项目

本 skill 的通用骨架提炼自以下 2api 项目（致谢）：

- [promptql2api](https://github.com/69gg/promptql2api) — Python+FastAPI，IREvent 架构 + 注册机（首选模板）
- [grok2api](https://github.com/69gg/grok2api) — 真流式 tool call 状态机、错误分类换号、多模态上传
- [gpt2api](https://github.com/69gg/gpt2api) — `<call>` prompt tool 协议、CJK token 估算、Sentinel POW
- [cursor2api](https://github.com/7836246/cursor2api) — 流式 warmup/guard 双缓冲、上下文压力治理

## 贡献

欢迎提 issue / PR。新增上游适配器范式、改进 tool call 解析、补充注册机 captcha 策略等都很有价值。

## License

MIT © Null <pylindex@qq.com>
