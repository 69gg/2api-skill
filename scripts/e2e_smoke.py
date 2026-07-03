#!/usr/bin/env python3
"""对运行中的 2api 网关跑端到端冒烟测试（跨生成项目通用，仅用标准库）。

用法：
    python scripts/e2e_smoke.py --base-url http://localhost:8088 --model <id> [--api-key <key>] [--suite models,chat,stream,tool]
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any


def http(base: str, path: str, method: str = "GET", body: Any = None,
         headers: dict[str, str] | None = None) -> tuple[int, str]:
    url = base.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser(description="2api 网关端到端冒烟")
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", default="gpt-4o")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--suite", default="models,chat,stream,tool")
    args = ap.parse_args()

    hdrs = {"Authorization": f"Bearer {args.api_key}"} if args.api_key else {}
    suite = [s.strip() for s in args.suite.split(",") if s.strip()]
    results: list[tuple[str, bool, str]] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        results.append((name, cond, detail))

    if "models" in suite:
        st, body = http(args.base_url, "/v1/models", headers=hdrs)
        check("GET /v1/models", st == 200 and '"data"' in body, f"HTTP {st}")

    if "chat" in suite:
        st, body = http(args.base_url, "/v1/chat/completions", "POST", {
            "model": args.model, "messages": [{"role": "user", "content": "say hi in one word"}],
        }, hdrs)
        check("POST /v1/chat/completions (non-stream)", st == 200, f"HTTP {st} {body[:80]}")

    if "stream" in suite:
        st, body = http(args.base_url, "/v1/chat/completions", "POST", {
            "model": args.model, "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        }, hdrs)
        check("POST /v1/chat/completions (stream)", st == 200 and "data:" in body, f"HTTP {st}")

    if "tool" in suite:
        st, body = http(args.base_url, "/v1/chat/completions", "POST", {
            "model": args.model, "messages": [{"role": "user", "content": "weather in beijing"}],
            "tools": [{"type": "function", "function": {
                "name": "get_weather", "description": "get weather",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}}}],
        }, hdrs)
        check("POST /v1/chat/completions (tool)", st == 200, f"HTTP {st} {body[:80]}")

    ok = True
    for name, cond, detail in results:
        ok = ok and cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {detail}")
    print("\n结果:", "全部通过 ✅" if ok else "有失败 ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
