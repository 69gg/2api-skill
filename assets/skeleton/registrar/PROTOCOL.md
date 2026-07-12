# {{Platform}} 注册机协议记录

> 本文档是注册流程的抓包记录，agent 在 SKILL.md 第 9-10 步走通注册流程后照填。
> 详细方法论见 skill 的 `references/registrar-protocol.md`。
> 节号固定；未启用的能力填 `N/A`，不要删节，避免与方法论文档对照错位。

## 一、入口 URL

- 注册页：`<填入>`
- 验证码发送端点：`<填入或 N/A>`
- 验证码验证端点：`<填入或 N/A>`
- 登录态获取端点：`<填入>`（如有 onboarding 步骤）

## 二、人机验证实测结论

<!-- FEATURE:captcha -->
- 是否有 captcha：`<是/否>`
- 类型：`<turnstile / recaptcha / 自定义>`
- sitekey：`<填入>`
- 实测结论：`<能否协议化？semi 无头过得了吗？需不需要手动点？>`
- 选定策略：`<semi / cdp / api>`
<!-- /FEATURE:captcha -->
<!-- FEATURE:no-captcha -->
- 是否有 captcha：否
- 选定策略：N/A（纯协议注册，未启用打码）
<!-- /FEATURE:no-captcha -->

## 三、注册请求序列

| 步骤 | 方法 | URL | headers | body | 关键返回字段 |
|---|---|---|---|---|---|
| 1 | `<填入>` | `<填入>` | `<填入>` | `<填入>` | `<填入>` |
| 2 | `<填入>` | `<填入>` | `<填入>` | `<填入>` | `<填入>` |

## 四、验证码提取（邮件 OTP）

<!-- FEATURE:email-otp -->
- 验证码邮件主题样本：`<填入>`
- 验证码邮件正文样本：`<填入>`
- 主题正则：`<填入>`
- 正文正则：`<填入>`
- 验证码长度：`<6>`（如不同请改）
<!-- /FEATURE:email-otp -->
<!-- FEATURE:no-email-otp -->
- 状态：N/A（注册无需邮件验证码；可用任意合规邮箱填表）
- 说明：不启用临时邮箱收件 / `poll_code`
<!-- /FEATURE:no-email-otp -->

## 五、凭据提取

- 凭据字段名：`<填入，见 app/upstream/account_fields.py>`
- 凭据位置：`<Set-Cookie / response body / localStorage>`

## 六、账号命名规则

- 用邮箱 localpart 命名（如 `user@example.com` → `user.json`），重名加 `-2/-3`。
