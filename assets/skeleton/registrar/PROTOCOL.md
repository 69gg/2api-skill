# {{Platform}} 注册机协议记录

> 本文档是注册流程的抓包记录，agent 在 SKILL.md 第 9-10 步走通注册流程后照填。
> 详细方法论见 `references/registrar-protocol.md`。

## 一、入口 URL

- 注册页：`<填入>`
- 验证码发送端点：`<填入>`
- 验证码验证端点：`<填入>`
- 登录态获取端点：`<填入>`（如有 onboarding 步骤）

## 二、人机验证实测结论

- 是否有 captcha：`<是/否>`
- 类型：`<turnstile / recaptcha / 自定义>`
- sitekey：`<填入>`
- 实测结论：`<能否协议化？semi 无头过得了吗？需不需要手动点？>`
- 选定策略：`<semi / cdp / api>`

## 三、注册请求序列

| 步骤 | 方法 | URL | headers | body | 关键返回字段 |
|---|---|---|---|---|---|
| 1 | POST | `/otp/send` | `<填入>` | `<填入>` | `<nonce>` |
| 2 | GET | `/api/mails` | `<填入>` | - | `<验证码>` |
| 3 | POST | `/otp/verify` | `<填入>` | `<填入>` | `<Set-Cookie: token>` |
| 4 | `<填入>` | `<填入>` | `<填入>` | `<填入>` | `<填入>` |

## 四、验证码提取

- 验证码邮件主题样本：`<填入>`
- 验证码邮件正文样本：`<填入>`
- 主题正则：`<填入>`
- 正文正则：`<填入>`
- 验证码长度：`<6>`（如不同请改）

## 五、凭据提取

- 凭据字段名：`<填入，见 app/upstream/account_fields.py>`
- 凭据位置：`<Set-Cookie / response body / localStorage>`

## 六、账号命名规则

- 用邮箱 localpart 命名（如 `user@example.com` → `user.json`），重名加 `-2/-3`。
