# Supabase Auth 逆向速查

> 适用于目标站使用标准 Supabase Auth（GoTrue）做注册/登录的 2api 项目。Superdesign 等站点走的就是这套：anon key + OTP/verify/refresh + 后续创建 workspace。

## 一、anon key 去哪里找

Supabase 前端需要 anon/public key 初始化 `supabase-js`，常见位置：

1. **JS bundle 明文搜索**（chrome-devtools Network 搜 `.js`）：
   - 关键字：`supabaseUrl`、`supabaseKey`、`createClient`、`anon`
   - 常见模式：
     ```js
     createClient("https://<project>.supabase.co", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...")
     ```
2. **HTML / 环境变量脚本**：`<script>window.__env = { SUPABASE_URL: "...", SUPABASE_ANON_KEY: "..." }</script>`
3. **LocalStorage / SessionStorage**：初始化后可能缓存 `supabase.auth.token`，里面也有 `access_token`。

anon key 权限低，只能做 `signUp` / `signInWithOtp` / `verifyOtp` / `refreshSession`，**不能读敏感表**，因此可以安全硬编码到注册机里。

## 二、核心端点

所有请求都要带两个头：

```http
apikey: <anon_key>
Authorization: Bearer <anon_key>
Content-Type: application/json
```

### 2.1 发送 OTP

```bash
curl -sS -X POST "https://<project>.supabase.co/auth/v1/otp" \
  -H "apikey: <anon_key>" \
  -H "Authorization: Bearer <anon_key>" \
  -H "Content-Type: application/json" \
  -d '{"email":"<temp-email>@<domain>"}'
```

- 也可以是 `"phone":"+1234567890"`（手机验证码）。
- 成功后服务器向邮箱/手机发送一次性验证码，无响应体（或返回空 JSON）。

### 2.2 验证 OTP / 注册并登录

```bash
curl -sS -X POST "https://<project>.supabase.co/auth/v1/verify" \
  -H "apikey: <anon_key>" \
  -H "Authorization: Bearer <anon_key>" \
  -H "Content-Type: application/json" \
  -d '{
    "type":"email",
    "email":"<temp-email>@<domain>",
    "token":"123456"
  }'
```

响应：

```json
{
  "access_token": "eyJ...",
  "refresh_token": "<uuid>",
  "expires_in": 3600,
  "token_type": "bearer",
  "user": { "id": "...", "email": "..." }
}
```

- 若邮箱未注册，验证成功后自动创建用户；已注册则直接登录。
- `access_token` 用于后续业务请求（`Authorization: Bearer <access_token>`）。

### 2.3 刷新 Token

`access_token` 默认 1 小时过期，注册机/网关需要 `refresh_token` 换新的：

```bash
curl -sS -X POST "https://<project>.supabase.co/auth/v1/token?grant_type=refresh_token" \
  -H "apikey: <anon_key>" \
  -H "Authorization: Bearer <anon_key>" \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"<refresh_token>"}'
```

响应同样返回新的 `access_token` + `refresh_token`。

### 2.4 刷新并发与 token 持久化

`refresh_token` **通常一次性**：第一个刷新请求成功后，旧的 `refresh_token` 立即失效。如果多 worker / 多进程同时刷新，第二个请求会拿到 `invalid refresh_token`，导致账号被误判失效。

骨架提供 `app/upstream/token_store.py`，用文件锁把“读旧 token → 刷新 → 写新 token”串行化：

```python
import httpx
from pathlib import Path
from app.upstream.token_store import load_token, locked_refresh

TOKEN_PATH = Path("account/<name>.token.json")

async def refresh_if_needed(old: dict) -> dict:
    """在文件锁内执行的实际刷新逻辑（同步函数，会被 locked_refresh 调用）。"""
    resp = httpx.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=refresh_token",
        headers={"apikey": ANON_KEY, "Authorization": f"Bearer {ANON_KEY}"},
        json={"refresh_token": old["refresh_token"]},
    )
    resp.raise_for_status()
    return resp.json()

# 在 AuthProvider.get_auth() 中检查 exp，接近过期时调用：
new_session = locked_refresh(TOKEN_PATH, refresh_if_needed)
```

- `locked_refresh` 使用 `fcntl.flock`，保证同一时刻只有一个进程/线程执行 `refresh_fn`。
- 刷新后把新的 `access_token` / `refresh_token` 写回 token 文件；`account/<name>.json` 中可只保留文件名引用或把 token 直接放 extra 字段。
- 若部署在 Windows，需把文件锁替换为 SQLite 或进程级锁。

## 三、业务层：常见还需要创建 workspace

很多 Supabase 应用在新用户登录后会调用自建端点创建默认 workspace/team，例如：

```bash
curl -sS -X POST "https://<project>.supabase.co/v1/teams" \
  -H "apikey: <anon_key>" \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"Personal"}'
```

- 端点路径因站而异，可能是 `/v1/teams`、`/v1/workspaces`、`/rest/v1/...`。
- 创建后返回的 `team_id` / `workspace_id` 常作为后续对话接口的必需参数，需写入 `account/<name>.json`。

## 四、注册机 pipeline 伪代码

```python
from registrar.email_client import create_email, poll_code
from registrar.http_client import HttpClient

SUPABASE_URL = cfg.upstream["supabase_url"]      # 见 config.toml.example
ANON_KEY = cfg.upstream["supabase_anon_key"]

def supabase_headers():
    return {"apikey": ANON_KEY, "Authorization": f"Bearer {ANON_KEY}"}

email = create_email(http, cfg.email.base_url, admin_auth=cfg.email.admin_auth)
address = email["address"]

# 1. 发 OTP
http.post_json(f"{SUPABASE_URL}/auth/v1/otp", {"email": address}, headers=supabase_headers())

# 2. 从临时邮箱收验证码
code = poll_code(http, cfg.email.base_url, jwt=email["jwt"],
                 subject_re=r"Your code[\s:]*(\d{6})",
                 body_re=r"(\d{6})")

# 3. 验证并拿 session
resp = http.post_json(f"{SUPABASE_URL}/auth/v1/verify",
                      {"type": "email", "email": address, "token": code},
                      headers=supabase_headers())
access_token = resp["access_token"]
refresh_token = resp["refresh_token"]

# 4. （若需要）创建 workspace
# team = http.post_json(f"{SUPABASE_URL}/v1/teams", {"name":"Personal"},
#                       headers={**supabase_headers(), "Authorization": f"Bearer {access_token}"})

acc = {
    "name": address.split("@")[0],
    "source_email": address,
    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    "disabled": False,
    "fail_reason": None,
    "cooldown_until": 0,
    "access_token": access_token,
    "refresh_token": refresh_token,
    # "team_id": team["id"],
}
write_account(cfg.account_dir, acc)
```

## 五、网关侧使用

`app/upstream/auth.py` 的 `get_auth()` 返回：

```python
return {"apikey": ANON_KEY, "Authorization": f"Bearer {self._account.access_token}"}
```

`is_auth_failure()` 检测到 401 / `jwt expired` / `token is expired` 时返回 True，触发 `app/deps.py` 换号或刷新逻辑。若需要自动刷新 access_token，可在 `get_auth()` 内用 `refresh_token` 调用 `/auth/v1/token` 再写回账号文件。

## 六、测试要点

- 验证 `/auth/v1/verify` 的验证码正则按真实邮件样本调整（常见 6 位数字）。
- `refresh_token` 只能使用一次，刷新后需要更新 `account/<name>.json`。
- Supabase 项目级 RLS 策略可能影响 `/rest/v1/` 访问；抓包确认业务端点是否走 PostgREST 还是自建 Edge Functions。
