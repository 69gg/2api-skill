"""注册流程编排（骨架 + 占位）。

注册步骤（按目标站抓包结果填入）：
    create_email → solve_captcha(若需) → 注册请求序列（send-otp/verify 等）→ 提取凭据 → 写盘 account/<name>.json

实现要点见 references/registrar-protocol.md。本函数提供编排骨架，具体步骤由你填入 TODO。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from registrar.email_client import create_email  # poll_code 在下方 TODO 用
from registrar.http_client import HttpClient
from registrar.models import RegistrarConfig


def register_one(
    cfg: RegistrarConfig,
    http: HttpClient,
    *,
    proxy: str | None = None,
    captcha_method: str | None = None,
) -> dict[str, Any]:
    """注册一个账号，返回账号 dict（含 name/source_email/created_at 及上游凭据字段）。

    成功后写入 account/<name>.json。失败抛异常（由 cli._safe_register 包装）。
    """
    # 1. 创建临时邮箱
    email = create_email(
        http, cfg.email.base_url,
        admin_auth=cfg.email.admin_auth,
        custom_auth=cfg.email.custom_auth,
        domain=cfg.email.domain,
    )
    address = email["address"]
    jwt = email["jwt"]  # noqa: F841 - 后续 poll_code 用；见下方 TODO 占位

    # 2. （若有 captcha）求解 captcha token
    # from registrar.captcha import solve
    # captcha_token = solve(cfg.captcha, url=REGISTER_URL, sitekey=SITEKEY)
    # TODO: 按目标站抓包结果填入 captcha sitekey 与 URL（见 references/registrar-protocol.md）

    # 3. 注册请求序列（按目标站抓包填入）
    # TODO: send-otp → poll_code → verify → 拿登录态 cookie/token
    # 示例（伪代码）：
    # http.post_json(f"{BASE}/otp/send", {"email": address, "captcha_token": captcha_token})
    # code = poll_code(http, cfg.email.base_url, jwt=jwt, custom_auth=cfg.email.custom_auth,
    #                  subject_re=..., body_re=...)  # 正则按目标站邮件样本确定
    # resp = http.post_json(f"{BASE}/otp/verify", {"email": address, "otp": code})
    # credentials = resp["headers"]["Set-Cookie"]  # 或 resp 里的 token
    raise NotImplementedError(
        "实现目标站的注册请求序列：create_email → solve_captcha(若需) → send-otp → poll_code → verify → 提取凭据。"
        "见 references/registrar-protocol.md 与 registrar/PROTOCOL.md。"
    )

    # 4. 组装账号 dict（含上游凭据字段）
    acc: dict[str, Any] = {
        "name": address.split("@")[0],  # 用邮箱 localpart 命名（重名加 -2/-3）
        "source_email": address,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "disabled": False,
        "fail_reason": None,
        "cooldown_until": 0,
        # TODO: 加入目标站凭据字段（见 app/upstream/account_fields.py）
    }

    # 5. 写盘（重名加 -2/-3）
    write_account(cfg.account_dir, acc)
    return acc


def write_account(account_dir: Path, acc: dict[str, Any]) -> Path:
    """把账号写入 account/<name>.json（重名加 -2/-3）。"""
    account_dir.mkdir(parents=True, exist_ok=True)
    name = acc["name"]
    target = account_dir / f"{name}.json"
    i = 1
    while target.is_file():
        target = account_dir / f"{name}-{i}.json"
        i += 1
    acc["name"] = target.stem
    with target.open("w", encoding="utf-8") as f:
        json.dump(acc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return target
