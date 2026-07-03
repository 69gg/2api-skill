# 抓包识别凭据流程

> 对应 SKILL.md 第 0-3 步。用 chrome-devtools MCP 抓真实请求 → 转 curl 本地验证 → 记录凭据。

## 一、第 0 步：询问需求

- 目标 webchat URL；
- 想要的端点（OpenAI Chat / Responses / Anthropic Messages）；
- 是否多账户、是否用 git、是否需要注册机；
- 同步说明局限（prompt tool call、人机验证、多模态依上游）。

## 二、第 1 步：用户先建账号

让用户**手动**在目标网站注册并登录一个账号（除非已有）。逆向需要真实登录态来抓凭据。

## 三、第 2 步：抓包（chrome-devtools MCP）

> MCP 工具名以实际枚举为准，下方为常见名。MCP 缺失时让用户在浏览器 DevTools 手动抓 Network。

1. `chrome-devtools:navigate_page` 导航到 webchat。
2. `chrome-devtools:list_network_requests`（过滤 XHR/fetch）观察请求。
3. 在网页发一条测试对话（如 "hi"）。
4. `chrome-devtools:get_network_request` 取关键的「发送消息」请求（通常 POST，返回 SSE/JSON 流）。
5. 必要时 `chrome-devtools:evaluate_script` 取 `localStorage`/`sessionStorage`/cookie/页面变量里的 token。
6. 如需图片上传，再发一条带图消息，抓上传请求。

`context7` 查上游相关库/协议文档辅助理解（如 GraphQL schema、SSE 规范）。

## 四、第 3 步：转 curl 本地验证

把抓到的请求 JSON 喂 `scripts/request_to_curl.py` 转成 curl，**本地实跑**验证能拿到回复：

```bash
echo '<请求JSON>' | python scripts/request_to_curl.py --redact   # 脱敏便于交流
echo '<请求JSON>' | python scripts/request_to_curl.py            # 实跑（含真实凭据）
```

**本步骤是阻塞项**，必须全部勾选才能继续：

- [ ] 请求 JSON 已转成 curl
- [ ] 本地实跑返回 200（或上游对应成功状态）
- [ ] 已识别凭据类型与字段名
- [ ] 已判断凭据有效期（优先长期有效；短时效需规划自动刷新）
- [ ] 已记录到 `account/main.json` 与 `app/upstream/account_fields.py`

> 未通过 curl 验证前，不要进入写代码阶段，更不要直接开注册机批量注册。否则 refresh_token 失效、visitor_id 校验失败等问题会被误以为是模型/注册机 bug。

## 五、识别凭据类型

| 类型 | 特征 |
|---|---|
| **Cookie** | 请求头 `Cookie: ...`（如 `sso=...`/`hasura-lux=...`），httpOnly cookie 可能需 evaluate_script 或 GM_cookie 跨域读 |
| **JWT/Bearer** | `Authorization: Bearer ...`；可能有刷新链（cookie → 临时 token → enriched JWT） |
| **会话 ID** | URL 参数或自定义头 |
| **签名头** | 如 `x-statsig`/`x-anthropic-billing-header`，需按前端逻辑生成（参考 grok2api/gpt2api） |

记录凭据字段后，填入 `account/main.json`（字段名记录在 `app/upstream/account_fields.py`）。

## 六、识别模型列表

观察上游是否有 `/models` API；若无，从网页模型选择器 UI 按钮 `data-testid`/`data-*` 提取，喂 `scripts/probe_catalog.py` 生成 `MODEL_CATALOG`（详见 `references/upstream-adapters.md`）。

## 七、识别上游协议

确认「发送对话」请求是 SSE / JSON Lines / 轮询 / 单次 POST，决定 `app/upstream/client.py` 的 `stream()` 实现方式（详见 `references/upstream-adapters.md`）。

## 八、识别人机验证

观察注册流程是否有 turnstile/captcha。有则注册机需走浏览器 + 打码（见 `references/registrar-protocol.md`）；无则协议化。

## 九、记录到 PROTOCOL

把抓包结论（端点、请求序列、凭据字段、协议、模型列表）记入 `app/upstream/` 实现与（若有注册机）`registrar/PROTOCOL.md`。
