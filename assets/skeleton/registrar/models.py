"""注册机配置：从 config.toml 读 [email] / [captcha] / [registry] / [proxy] 段。

与主程序 :mod:`app.config` 共用同一个 config.toml：主程序读
[gateway]/[upstream]/[registry]/[admin]/[proxy]，注册机读
[email]/[captcha]/[registry]/[proxy]。
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
    proxy_url: str = ""       # 可选覆盖；空则用 RegistrarConfig.proxy_url
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
    # 已解析：registrar_url 优先，否则回退 [proxy].url；皆空为 ""
    proxy_url: str = ""

    def effective_proxy(self) -> str | None:
        """HTTP / captcha 用代理；未配置返回 ``None``（直连）。"""
        p = (self.proxy_url or "").strip()
        return p or None


def _resolve_proxy(data: dict[str, Any]) -> str:
    """解析注册机代理：``[proxy].registrar_url`` → ``[proxy].url`` → 空。"""
    proxy = data.get("proxy") or {}
    if not isinstance(proxy, dict):
        return ""
    registrar = str(proxy.get("registrar_url") or proxy.get("registrar") or "").strip()
    default = str(proxy.get("url") or proxy.get("default") or "").strip()
    return registrar or default


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
    proxy_url = _resolve_proxy(data)
    # captcha.proxy_url 空时回退到注册机代理（便于 semi 浏览器走同一代理）
    if not (captcha.proxy_url or "").strip() and proxy_url:
        captcha.proxy_url = proxy_url
    return RegistrarConfig(
        email=email,
        captcha=captcha,
        account_dir=account_dir,
        config_path=p,
        upstream=upstream,
        proxy_url=proxy_url,
    )
