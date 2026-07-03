"""端到端测试：用 OpenAI SDK 打本地网关跑普通对话。先起网关再跑。

用法：uv run python -m scripts.e2e_chat --base-url http://localhost:8088 --model <id> [--api-key <key>]
"""
from __future__ import annotations

import argparse
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description="对话端到端测试")
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
    r = client.chat.completions.create(
        model=args.model,
        messages=[{"role": "user", "content": "用一句话介绍自己"}],
    )
    print("非流式:", r.choices[0].message.content)
    print("usage:", r.usage)
    print("流式:", end=" ", flush=True)
    for chunk in client.chat.completions.create(
        model=args.model, stream=True,
        messages=[{"role": "user", "content": "数到 3"}],
    ):
        d = chunk.choices[0].delta
        if d.content:
            print(d.content, end="", flush=True)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
