"""人机验证求解器（多策略）。

三策略：semi（有头浏览器自动/手动点）/ cdp（连已开 debug chrome）/ api（打码服务）。
接口 ``solve(url, sitekey, timeout_ms) -> str`` 返回 captcha token。
详见 references/registrar-protocol.md。

playwright 是可选依赖（``uv sync --extra registrar``），缺失时 semi/cdp 不可用，需用 api 策略。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from registrar.models import CaptchaConfig


def solve(config: CaptchaConfig, *, url: str, sitekey: str, timeout_ms: int = 180_000) -> str:
    """按 config.method 选策略求解 captcha token。"""
    method = (config.method or "semi").lower()
    if method == "api":
        return _solve_api(config, url, sitekey, timeout_ms)
    if method == "cdp":
        return _solve_cdp(config, url, sitekey, timeout_ms)
    return _solve_semi(config, url, sitekey, timeout_ms)


def _solve_semi(config: CaptchaConfig, url: str, sitekey: str, timeout_ms: int) -> str:
    """semi：playwright 弹有头浏览器到登录页，循环读 input[name="cf-turnstile-response"]，自动过或人手点。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError(
            "semi 策略需要 playwright（uv sync --extra registrar）；或改用 api 策略（打码服务）"
        ) from e
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.headless, proxy={"server": config.proxy_url} if config.proxy_url else None)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded")
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            try:
                token = page.locator('input[name="cf-turnstile-response"]').input_value()
                if token:
                    browser.close()
                    return token
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.5)
        browser.close()
        raise RuntimeError("semi: timeout waiting for captcha token")


def _solve_cdp(config: CaptchaConfig, url: str, sitekey: str, timeout_ms: int) -> str:
    """cdp：连已开 debug chrome（--remote-debugging-port），真实指纹自动过。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError("cdp 策略需要 playwright") from e
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(config.cdp_endpoint or "http://localhost:9222")
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            try:
                token = page.locator('input[name="cf-turnstile-response"]').input_value()
                if token:
                    page.close()
                    ctx.close()
                    return token
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.5)
        page.close()
        ctx.close()
        raise RuntimeError("cdp: timeout waiting for captcha token")


def _solve_api(config: CaptchaConfig, url: str, sitekey: str, timeout_ms: int) -> str:
    """api：打码服务（如 CapSolver）。需填 [captcha].api_key。"""
    if not config.api_key:
        raise RuntimeError("api 策略需要 [captcha].api_key")
    provider = config.api_provider or "capsolver"
    if provider != "capsolver":
        raise NotImplementedError(f"打码服务 {provider} 未实现，仅支持 capsolver")
    return _solve_capsolver(config, url, sitekey, timeout_ms)


def _solve_capsolver(config: CaptchaConfig, url: str, sitekey: str, timeout_ms: int) -> str:

    def _post(path: str, body: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(body).encode()
        req = urllib.request.Request(f"https://api.capsolver.com{path}", data=data,
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return json.loads(e.read().decode(errors="replace"))

    created = _post("/createTask", {
        "clientKey": config.api_key,
        "task": {"type": "AntiTurnstileTaskProxyLess", "websiteURL": url, "websiteKey": sitekey},
    })
    task_id = created.get("taskId")
    if not task_id:
        raise RuntimeError(f"capsolver createTask failed: {created}")
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        time.sleep(3)
        r = _post("/getTaskResult", {"clientKey": config.api_key, "taskId": task_id})
        if r.get("status") == "ready":
            return r["solution"]["token"]
        if r.get("errorId"):
            raise RuntimeError(f"capsolver failed: {r}")
    raise RuntimeError("capsolver timeout")
