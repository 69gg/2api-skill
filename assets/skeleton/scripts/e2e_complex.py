"""端到端测试：多轮对话 + 多模态（若支持）+ system prompt 拼接。先起网关再跑。

用法：uv run python -m scripts.e2e_complex --base-url http://localhost:8088 --model <id> [--image path/to/img.png]
"""
from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="多轮+多模态测试")
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--api-key", default="")
    ap.add_argument("--image", default=None, help="图片路径（测多模态上传，若上游支持）")
    args = ap.parse_args()
    try:
        from openai import OpenAI
    except ImportError:
        print("需 openai SDK：uv sync --extra dev", file=sys.stderr)
        return 1
    client = OpenAI(base_url=args.base_url, api_key=args.api_key or "dummy")
    # 多轮对话（含 system prompt + tool result）
    messages = [
        {"role": "system", "content": "你是一个简洁的助手，每句不超过 20 字。"},
        {"role": "user", "content": "我叫小明。"},
        {"role": "assistant", "content": "记住了，小明。"},
        {"role": "user", "content": "我叫什么？"},
    ]
    r = client.chat.completions.create(model=args.model, messages=messages)
    print("多轮记忆:", r.choices[0].message.content)
    # 多模态（若支持）
    if args.image:
        img = Path(args.image).read_bytes()
        b64 = base64.b64encode(img).decode()
        r = client.chat.completions.create(
            model=args.model,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": "这张图里有什么？"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]}],
        )
        print("多模态:", r.choices[0].message.content[:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
