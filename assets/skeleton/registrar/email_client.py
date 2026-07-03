"""cf-temp-email 临时邮箱客户端（通用，与目标站无关）。

鉴权四件套：x-admin-auth（创建）/ Authorization: Bearer <jwt>（收件）/ x-custom-auth（站点密码，若有）。
详见 references/registrar-protocol.md。
"""
from __future__ import annotations

import re
import secrets
import time
from typing import Any

from registrar.http_client import HttpClient


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
        # 部分 cf-temp-email 部署对 name="" 返回 400，自动兜底一段随机 localpart
        name = secrets.token_hex(8)
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
