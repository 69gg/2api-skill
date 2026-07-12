"""邮箱工具：cf-temp-email 客户端（需 OTP）+ 本地随机合规邮箱（无需 OTP）。

鉴权四件套：x-admin-auth（创建）/ Authorization: Bearer <jwt>（收件）/ x-custom-auth（站点密码，若有）。
详见 references/registrar-protocol.md。
"""
from __future__ import annotations

import re
import secrets
import string
import time
from typing import Any, Sequence

from registrar.http_client import HttpClient

# 无需 OTP 时轮换的常见消费级域名（每次随机挑一个，避免整池同域）。
# 仅作「格式合规 + 唯一」填表用，不保证可收信。
_FAKE_EMAIL_DOMAINS: tuple[str, ...] = (
    "gmail.com",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "icloud.com",
    "proton.me",
    "protonmail.com",
    "mail.com",
    "gmx.com",
    "gmx.net",
    "yandex.com",
    "aol.com",
    "zoho.com",
    "fastmail.com",
    "tutanota.com",
    "mail.ru",
    "qq.com",
    "163.com",
    "126.com",
    "yeah.net",
    "sina.com",
    "sohu.com",
    "foxmail.com",
    "me.com",
    "msn.com",
    "inbox.com",
    "hushmail.com",
    "tuta.io",
    "pm.me",
)

_LOCAL_ALPHA = string.ascii_lowercase
_LOCAL_ALNUM = string.ascii_lowercase + string.digits


def random_localpart(*, min_len: int = 10, max_len: int = 18) -> str:
    """高熵 localpart：字母开头 + 随机字母数字（长度可抖动）。"""
    n = secrets.randbelow(max(1, max_len - min_len + 1)) + min_len
    # 部分站点要求 local 以字母开头、不含连续特殊字符
    first = secrets.choice(_LOCAL_ALPHA)
    rest = "".join(secrets.choice(_LOCAL_ALNUM) for _ in range(n - 1))
    # 再拼一段 hex 提升碰撞，避免纯可猜测序列
    suffix = secrets.token_hex(3)
    return f"{first}{rest}{suffix}"[: max(max_len + 6, n + 6)]


def generate_random_email(
    *,
    domains: Sequence[str] | None = None,
    domain: str | None = None,
) -> str:
    """无需邮件 OTP 时本地生成合规邮箱字符串。

    - **多域名**：默认从内置池随机选域名，避免批量注册全用同一 domain。
    - **高熵 localpart**：``secrets`` 生成，长度抖动。
    - ``domain`` 若显式传入则固定该域（兼容旧调用）；否则 ``domains`` 池随机，
      再否则用内置 ``_FAKE_EMAIL_DOMAINS``。
    """
    if domain and domain.strip():
        chosen = domain.strip().lstrip("@")
    else:
        pool = [d.strip().lstrip("@") for d in (domains or _FAKE_EMAIL_DOMAINS) if d and str(d).strip()]
        if not pool:
            pool = list(_FAKE_EMAIL_DOMAINS)
        chosen = secrets.choice(pool)
    return f"{random_localpart()}@{chosen}"


def create_email(
    http: HttpClient,
    base_url: str,
    *,
    admin_auth: str,
    custom_auth: str = "",
    domain: str = "",
    name: str = "",
) -> dict[str, Any]:
    """管理员方式创建临时邮箱，返回 {address, jwt, address_id}。"""
    if not name:
        # 部分 cf-temp-email 部署对 name="" 返回 400，自动兜底高熵 localpart
        name = random_localpart(min_len=8, max_len=14)
    headers = {"x-admin-auth": admin_auth}
    if custom_auth:
        headers["x-custom-auth"] = custom_auth
    body = {"name": name, "enablePrefix": False, "domain": domain}
    resp = http.post_json(f"{base_url}/admin/new_address", body, headers=headers)
    if resp["status_code"] != 200:
        raise RuntimeError(f"create_email failed: {resp['status_code']} {resp['text'][:200]}")
    data = resp["text"]
    import json
    parsed = json.loads(data)
    return {"address": parsed["address"], "jwt": parsed["jwt"], "address_id": parsed.get("address_id")}


def poll_code(
    http: HttpClient,
    base_url: str,
    *,
    jwt: str,
    custom_auth: str = "",
    subject_re: str = r"sign-in code[:\s]*(\d{6})",
    body_re: str = r"letter-spacing[^>]*>\s*(\d{6})",
    poll_interval: float = 1.5,
    timeout: float = 120,
) -> str:
    """轮询收件箱，提取验证码（默认 6 位数字）。返回验证码字符串。"""
    headers = {"Authorization": f"Bearer {jwt}"}
    if custom_auth:
        headers["x-custom-auth"] = custom_auth
    deadline = time.time() + timeout
    seen: set[str] = set()
    while time.time() < deadline:
        resp = http.get(f"{base_url}/api/mails?limit=10&offset=0", headers=headers)
        if resp["status_code"] != 200:
            time.sleep(poll_interval)
            continue
        import json
        data = json.loads(resp["text"])
        for mail in data.get("results", []):
            mid = str(mail.get("id", ""))
            if mid in seen:
                continue
            seen.add(mid)
            raw = mail.get("raw", "") or ""
            for pat in (subject_re, body_re):
                m = re.search(pat, raw)
                if m:
                    return m.group(1)
        time.sleep(poll_interval)
    raise RuntimeError(f"poll_code timeout after {timeout}s")
