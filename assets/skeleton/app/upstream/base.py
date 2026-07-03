"""上游适配器接口契约（换目标网站时实现这些；详见 references/upstream-adapters.md）。

5 个角色：
- :class:`AuthProvider`：认证（get_auth 返回请求头/cookie；is_auth_failure 判定失效）。
- :class:`UpstreamClient`：上游请求（``stream(prompt, model_id) → IREvent`` 流；多模态上传）。
- :class:`EventParser`：原生事件 → IREvent（**换上游唯一核心改动**）。
- :class:`ModelRegistry`：模型目录（catalog / normalize / upstream_id_for）。
- tool 策略（native 直通 / prompt 注入解析）由 settings.upstream_strategy 决定。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Literal

from app.account import FailReason
from app.events import IREvent

# 默认的失效 body 关键词（可按目标站在 AuthProvider.classify_failure 中覆盖）。
_AUTH_HINTS = ("unauthorized", "invalid token", "not authenticated", "login required")
_BAN_HINTS = ("banned", "suspended", "disabled", "forbidden", "封禁", "封号")
_QUOTA_HINTS = ("quota", "limit reached", "insufficient", "credit", "额度", "配额", "余额不足")
_CF_HINTS = ("cloudflare", "captcha", "turnstile", "challenge", "验证码")


class AuthProvider(ABC):
    @abstractmethod
    async def get_auth(self) -> dict[str, str]:
        """返回要注入上游请求的头/cookie（如 {"Authorization": "Bearer ..."} 或 {"Cookie": ...}）。"""

    @abstractmethod
    def is_auth_failure(self, exc: BaseException) -> bool:
        """判断异常是否为账号认证失败（喂给 app.deps.classify_failure）。"""

    def classify_failure(self, exc: BaseException) -> FailReason | None:
        """把上游异常映射成 FailReason。

        默认实现按 HTTP 状态码 + body 关键词分类；按目标站覆盖本方法即可自定义
        （如 Superdesign 的额度耗尽、Pro 模型错误、visitor_id 校验失败等）。
        返回 ``None`` 表示非账号级失效，deps 会回退到通用逻辑。
        """
        status: int | None = None
        body = ""
        import httpx

        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            try:
                body = exc.response.text.lower()
            except Exception:  # noqa: BLE001
                body = ""
        text = f"{body} {str(exc).lower()}"
        if status in (401, 403) or any(h in text for h in _AUTH_HINTS):
            return FailReason.AUTH_FAILED
        if status == 429 or any(h in text for h in _QUOTA_HINTS):
            return FailReason.QUOTA_EXHAUSTED
        if status == 451 or any(h in text for h in _CF_HINTS):
            return FailReason.CF_CHALLENGE
        if any(h in text for h in _BAN_HINTS):
            return FailReason.BANNED
        return None


class UpstreamClient(ABC):
    @abstractmethod
    async def stream(self, prompt: str, model_id: str | None = None, **kw: Any) -> AsyncIterator[IREvent]:
        """发送 prompt 到上游，yield IREvent 流。"""

    async def upload_image(self, data: bytes, mime: str, filename: str = "") -> str:
        """多模态：上传图片，返回上游引用（url/id）。默认不支持，上游按范式实现。"""
        raise NotImplementedError(
            "该上游未实现图片上传；参考 references/upstream-adapters.md 的两种上传范式。")

    async def upload_file(self, data: bytes, mime: str, filename: str = "") -> str:
        raise NotImplementedError("该上游未实现文件上传；参考 references/upstream-adapters.md。")


class EventParser(ABC):
    @abstractmethod
    def parse(self, raw: Any) -> list[IREvent]:
        """把上游单个原生事件（dict/bytes/str）解析成 0..n 个 IREvent。换上游唯一核心改动。"""


class ModelRegistry(ABC):
    @abstractmethod
    def catalog(self) -> list[dict[str, Any]]:
        """模型目录：[{"id", "name", "owner", "upstream_id"}]。"""

    @abstractmethod
    def normalize(self, model: str | None) -> str:
        """客户端传入的 model → catalog id。"""

    @abstractmethod
    def upstream_id_for(self, model_id: str) -> str | None:
        """catalog id → 上游真实模型标识（如上游 model name / llm_config_id）。"""


ToolStrategy = Literal["native", "prompt"]
