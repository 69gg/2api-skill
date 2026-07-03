"""端到端测试：tool call 命中率统计。先起网关再跑。

用法：uv run python -m scripts.e2e_tool --base-url http://localhost:8088 --model <id> [--api-key <key>]
"""
from __future__ import annotations

import argparse
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description="tool call 命中率测试")
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--api-key", default="")
    args = ap.parse_args()
    try:
        from openai import OpenAI
    except ImportError:
        print("需 openai SDK：uv sync --extra dev", file=sys.stderr)
        return 1
    client = OpenAI(base_url=args.base_url, api_key=args.api_key or "dummy")
    cases = [
        ("查北京天气", {"type": "function", "function": {
            "name": "get_weather", "description": "查询某地天气",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}},
                           "required": ["city"]}}}),
        ("打开 https://example.com", {"type": "function", "function": {
            "name": "open_url", "description": "打开网址",
            "parameters": {"type": "object", "properties": {"url": {"type": "string"}},
                           "required": ["url"]}}}),
        ("算一下 12 * 8", {"type": "function", "function": {
            "name": "calculate", "description": "计算表达式",
            "parameters": {"type": "object", "properties": {"expr": {"type": "string"}},
                           "required": ["expr"]}}}),
    ]
    hit = 0
    for q, tool in cases:
        r = client.chat.completions.create(
            model=args.model,
            messages=[{"role": "user", "content": q}],
            tools=[tool],
        )
        msg = r.choices[0].message
        if msg.tool_calls:
            tc = msg.tool_calls[0]
            print(f"[HIT] {q} -> {tc.function.name}({tc.function.arguments})")
            hit += 1
        else:
            print(f"[MISS] {q} -> {msg.content[:80]}")
    print(f"\n命中率: {hit}/{len(cases)}")
    return 0 if hit else 1


if __name__ == "__main__":
    raise SystemExit(main())
