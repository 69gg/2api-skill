"""网关配置：从 config.toml 加载（pydantic.BaseModel + tomllib，无 pydantic-settings）。

``config.toml`` 只放「与账号无关」的配置（网关 / 行为 / 上游 / 注册机）；
每个账号凭据存 ``account/<name>.json``，由 :mod:`app.account` 管理。
"""
from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    """网关行为与端点配置（不含账号凭据）。"""

    # 网关监听
    host: str = "0.0.0.0"
    port: int = 8088
    gateway_api_key: str = ""  # 客户端访问网关用的 key；空则不校验（/v1 无认证）

    # 上游通用行为参数（与具体网站无关）
    request_timeout: float = 120.0  # 单次请求总超时（秒）
    poll_interval: float = 1.2  # 轮询式上游的轮询间隔（秒）
    token_refresh_margin: int = 300  # 凭据到期前多少秒主动刷新
    tool_call_retries: int = 3  # prompt 模式被拒绝/识破时换角度重试次数（0=不重试）

    # 上游专属占位字段（目标网站的端点/参数在 config.toml.example 的 [upstream] 段扩展）
    upstream_chat_url: str = ""  # 上游「发送对话」端点
    upstream_strategy: str = "prompt"  # tool 策略：prompt（注入解析）/ native（上游原生直通）

    # 账号凭据目录（相对工作目录；account/<name>.json，gitignored）
    account_dir: str = "account"

    # 管理后台鉴权（/admin/*）；空=关闭 admin 端点（返回 404 隐藏存在）
    admin_auth_key: str = ""


def _flatten_toml(data: dict) -> dict:
    """平铺 [gateway]/[upstream]/[registry]/[admin] 四段；忽略 [email]/[captcha]（仅注册机用）。

    toml 简短键名映射到 Settings 字段（``api_key`` → ``gateway_api_key``，
    ``auth_key`` → ``admin_auth_key``）。
    """
    flat: dict = {}
    for section in ("gateway", "upstream", "registry", "admin"):
        flat.update(data.get(section, {}))
    if "api_key" in flat and "gateway_api_key" not in flat:
        flat["gateway_api_key"] = flat.pop("api_key")
    if "auth_key" in flat and "admin_auth_key" not in flat:
        flat["admin_auth_key"] = flat.pop("auth_key")
    return flat


@lru_cache(maxsize=8)
def get_settings(path: str | None = None) -> Settings:
    """加载 config.toml 构造 Settings。

    ``path`` 默认 ``$TWOAPI_CONFIG`` 或 ``config.toml``。文件缺失时回退全默认值。
    被 :func:`clear_settings_cache` 用于测试重读。
    """
    p = path or os.getenv("TWOAPI_CONFIG", "config.toml")
    fpath = Path(p)
    if not fpath.is_file():
        return Settings()
    with fpath.open("rb") as f:
        data = tomllib.load(f)
    return Settings(**_flatten_toml(data))


def clear_settings_cache() -> None:
    """清空 get_settings 的 lru_cache，供测试重读配置。"""
    get_settings.cache_clear()
