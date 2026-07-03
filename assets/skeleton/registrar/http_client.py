"""注册机 HTTP 客户端（curl_cffi impersonate chrome，绕过 CF UA/IP 限流）。

curl-cffi 是可选依赖（``uv sync --extra registrar``），缺失时降级到 httpx。
"""
from __future__ import annotations

from typing import Any

try:
    from curl_cffi import requests as _curl  # type: ignore[import-untyped]
    _HAS_CURL = True
except ImportError:  # pragma: no cover - 仅当未装 registrar extra 时
    _HAS_CURL = False


class HttpClient:
    def __init__(self, *, proxy: str | None = None) -> None:
        self._proxy = proxy or None

    def request(self, method: str, url: str, **kw: Any) -> dict[str, Any]:
        """发请求，返回 dict: {status_code, headers, text}。"""
        if _HAS_CURL:
            kw.setdefault("impersonate", "chrome131")
            r = _curl.request(method, url, proxies={"http": self._proxy, "https": self._proxy} if self._proxy else None,
                              timeout=120, **kw)
            return {"status_code": r.status_code, "headers": dict(r.headers), "text": r.text}
        # 降级到 httpx
        import httpx
        with httpx.Client(proxy=self._proxy, timeout=120) as c:
            r = c.request(method, url, **kw)
            return {"status_code": r.status_code, "headers": dict(r.headers), "text": r.text}

    def post_json(self, url: str, body: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        return self.request("POST", url, json=body, headers={"Content-Type": "application/json", **(headers or {})})

    def get(self, url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        return self.request("GET", url, headers=headers or {})
