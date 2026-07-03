# 注册机协议与实现

> 对应 SKILL.md 第 8-11 步。代码在 `app/.../registrar/`（骨架在 `assets/skeleton/registrar/`）。本节给出 cf-temp-email API、验证码正则、captcha 三策略。

## 一、cf-temp-email（Cloudflare 临时邮箱）API

收件箱用开源项目 [dreamhunter2333/cloudflare_temp_email](https://github.com/dreamhunter2333/cloudflare_temp_email)。本节给出可直接照抄的端点与鉴权。

### 1.1 鉴权四件套

| 头 | 作用 | 何时用 |
|---|---|---|
| `x-custom-auth` | 站点访问密码（全局） | 服务端配了访问密码时所有 `/api/*`、`/admin/*` 都要带 |
| `Authorization: Bearer <jwt>` | 邮箱地址令牌 | 操作单个邮箱的 `/api/*` 端点（列邮件、读邮件、删邮件） |
| `x-admin-auth` | 管理员密码 | 所有 `/admin/*` 端点（管理员创建邮箱、列出全部地址） |
| `x-user-token` | 用户账号 JWT | `/user_api/*`（注册/登录账号体系，非必需） |

**2api 注册机场景**：
- 创建邮箱用 `x-admin-auth` + `x-custom-auth`(若有)；
- 收邮件用 `Authorization: Bearer <jwt>` + `x-custom-auth`(若有)；
- 创建与收件用同一个 jwt（创建时返回），无需额外登录。

### 1.2 创建临时邮箱（管理员方式）

```bash
curl -sS -X POST 'https://temp-mail.example.com/admin/new_address'   -H 'Content-Type: application/json'   -H 'x-admin-auth: ADMIN_PASS'   -H 'x-custom-auth: SITE_PASS'   -d '{"name":"pqabc123","enablePrefix":false,"domain":"mail.example.com"}'
# 响应: {"address":"pqabc123@mail.example.com","jwt":"eyJ...","address_id":42}
```

- `name` 留空 → 服务端随机生成；`enablePrefix=false` 建无前缀邮箱（管理员接口）；
- `domain` 必须在服务端允许域名列表内；
- `/admin/new_address` **不受限速、不需 cf_token**，最适合自动化注册机。

### 1.3 列出收件箱（轮询验证码）

```bash
curl -sS 'https://temp-mail.example.com/api/mails?limit=10&offset=0'   -H 'Accept: application/json'   -H 'Authorization: Bearer <jwt>'   -H 'x-custom-auth: SITE_PASS'
# 响应: {"results":[{"id":"12345","raw":"<完整 RFC822 原文，含 Subject+body>"}],"offset":0,"size":1}
```

`results[].raw` **已含完整邮件原文**（Subject + HTML body），无需再拉单封即可正则提取验证码。

## 二、验证码提取正则

从邮件 `raw` 提取（每 1.5s 轮询至超时）：

```python
import re
# 主题
SUBJECT_RE = re.compile(r"sign-in code[:\s]*(\d{6})")
# 正文兜底（HTML 邮件里数字常被 letter-spacing 包裹）
BODY_RE = re.compile(r"letter-spacing[^>]*>\s*(\d{6})")
```

**注意**：每个站点的验证码邮件格式不同，需在抓包阶段（SKILL.md 第 9 步）用真实邮件样本确定正则，不要硬编码假设格式。

## 三、captcha 三策略

注册流程若有人机验证（turnstile/captcha），按以下策略选一：

| 策略 | 实现 | 适用 |
|---|---|---|
| **semi**（默认） | playwright 弹**有头**浏览器到登录页，循环读 `input[name="cf-turnstile-response"]`，检测到 token 自动继续；可人手点 widget。**无头通常过不了**（参考 promptql2api 实测） | 多数站点 |
| **cdp** | playwright `connect_over_cdp` 连你已开的 debug chrome（`--remote-debugging-port=9222`），**真实指纹自动过**；只关 page 不断 CDP | 有现成 debug chrome 的场景 |
| **api** | 打码服务（如 CapSolver）：`createTask` → 轮询 `getTaskResult`，无浏览器 | 愿付费、可全自动 |

## 四、注册流程编排（`registrar/pipeline.py:register_one`）

```text
1. create_email() → 拿临时邮箱地址 + jwt
2. （若有 captcha）solve_captcha() → 拿 token
3. 注册请求序列（按目标站抓包结果填）：
   - send OTP → 拿 nonce
   - poll_code() → 从邮箱取验证码（用上面的正则）
   - verify OTP → 拿登录态 cookie/token
4. （可选）拉取项目信息（如 promptql 的 project_id）
5. 写盘 account/<name>.json（用邮箱 localpart 命名，重名加 -2/-3）
```

`pipeline.py` 是编排骨架，注册步骤（按目标站定制）由你填入；`email_client.py`/`http_client.py` 已通用写全。

## 五、CLI（`registrar/cli.py`）

```bash
uv run python -m registrar -n 3 -w 2 --captcha-method semi
```

- `-n/--count`：注册数量（0=无限）；
- `-w/--workers`：并发数（ThreadPoolExecutor）；
- `--proxy`：可选代理；
- `--config`：配置文件路径；
- `--captcha-method`：semi/cdp/api。

单账号失败不致命（`_safe_register` 包装异常），并发跑满 `-w` 个任务。

## 六、PROTOCOL.md（记录模板）

`registrar/PROTOCOL.md` 是注册协议记录模板，agent 抓包后照填：
- 入口 URL；
- captcha 实测结论（能否协议化）；
- 注册请求序列表（URL/方法/headers/body）；
- 凭据提取位置；
- 验证码正则（来自真实邮件样本）。

## 七、参考实现

- cf-temp-email 完整实现：`/data1/promptql2api/registrar/email_client.py`（权威）；
- captcha 三策略：`/data1/promptql2api/registrar/turnstile.py`（通用化为 captcha.py）。
