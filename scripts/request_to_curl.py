#!/usr/bin/env python3
"""把抓到的网络请求（如 chrome-devtools get_network_request 的返回）转成可运行的 curl 命令。

用法：
    echo '<请求JSON>' | python scripts/request_to_curl.py [--redact]
    python scripts/request_to_curl.py --request '<请求JSON>' [--redact]

输入 JSON 字段：url / method / headers（dict 或 [{name,value}]）/ postData（或 body / data）。
--redact：把 cookie/token 类头脱敏为 <...>，便于交流。
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
from typing import Any

_SENSITIVE = ("cookie", "authorization", "x-csrf", "token", "api-key", "apikey")


def _normalize_headers(headers: Any) -> dict[str, str]:
    if isinstance(headers, dict):
        return {str(k): str(v) for k, v in headers.items()}
    if isinstance(headers, list):
        out: dict[str, str] = {}
        for h in headers:
            if isinstance(h, dict) and "name" in h:
                out[str(h["name"])] = str(h.get("value", ""))
        return out
    return {}


def to_curl(req: dict[str, Any], redact: bool = False) -> str:
    method = str(req.get("method", "GET")).upper()
    url = str(req.get("url", ""))
    headers = _normalize_headers(req.get("headers"))
    parts: list[str] = ["curl -sS", f"-X {shlex.quote(method)}", shlex.quote(url)]
    for k, v in headers.items():
        if redact and any(s in k.lower() for s in _SENSITIVE):
            v = f"<{k.lower()}>"
        parts.append(f"-H {shlex.quote(f'{k}: {v}')}")
    body = req.get("postData") or req.get("body") or req.get("data")
    if body:
        if not isinstance(body, str):
            body = json.dumps(body, ensure_ascii=False)
        parts.append(f"--data-raw {shlex.quote(body)}")
    parts.append("--compressed")
    return " \\\n  ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description="请求 JSON → curl 命令")
    ap.add_argument("--request", help="请求 JSON（不给则读 stdin）")
    ap.add_argument("--redact", action="store_true", help="脱敏 cookie/token")
    args = ap.parse_args()
    raw = args.request if args.request else sys.stdin.read()
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"JSON 解析失败: {e}", file=sys.stderr)
        return 1
    print(to_curl(req, args.redact))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
