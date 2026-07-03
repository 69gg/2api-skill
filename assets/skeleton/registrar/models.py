"""注册机配置：从 config.toml 读 [email] / [captcha] / [registry] 段。

与主程序 :mod:`app.config` 共用同一个 config.toml：主程序读
[gateway]/[upstream]/[registry]/[admin]，注册机读 [email]/[captcha]/[registry]。
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EmailConfig:
    """Cloudflare Temp Email 服务配置（dreamhunter2333/cloudflare_temp_email）。"""

    base_url: str = ""
    admin_auth: str = ""
    custom_auth: str = ""
    domain: str = ""
    poll_timeout: int = 120  # 等待验证邮件的最长秒数


@dataclass
class CaptchaConfig:
    """人机验证求解器配置（多策略，见 registrar/captcha.py）。"""

    method: str = "semi"      # semi（默认，有头浏览器自动/手动点）/ cdp（连 debug chrome）/ api（打码）
    headless: bool = False    # semi 策略用
    proxy_url: str = ""
    cdp_endpoint: str = ""    # cdp 策略，如 http://localhost:9222
    api_provider: str = ""    # api 策略，如 capsolver（默认）
    api_key: str = ""         # api 策略


@dataclass
class RegistrarConfig:
    """注册机运行配置。"""

    email: EmailConfig
    captcha: CaptchaConfig
    account_dir: Path
    config_path: str = ""
    upstream: dict[str, Any] = field(default_factory=dict)


def load_registrar_config(path: str | None = None) -> RegistrarConfig:
    """从 config.toml 加载注册机配置。``path`` 默认 ``$TWOAPI_CONFIG`` 或 ``config.toml``。"""
    p = path or os.getenv("TWOAPI_CONFIG", "config.toml")
    fpath = Path(p)
    if not fpath.is_file():
        raise FileNotFoundError(
            f"config.toml 未找到: {fpath}（复制 config.toml.example 为 config.toml 并填值）"
        )
    with fpath.open("rb") as f:
        data = tomllib.load(f)
    email = EmailConfig(**data.get("email", {}))
    captcha = CaptchaConfig(**data.get("captcha", {}))
    account_dir = Path(data.get("registry", {}).get("account_dir", "account"))
    upstream = data.get("upstream", {})
    return RegistrarConfig(
        email=email, captcha=captcha, account_dir=account_dir, config_path=p, upstream=upstream
    )
