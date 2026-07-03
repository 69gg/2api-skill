"""端到端测试：列出 /v1/models 并打印。"""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request


def main() -> int:
    ap = argparse.ArgumentParser(description="模型列表测试")
    ap.add_argument("--base-url", required=True)
    args = ap.parse_args()
    try:
        with urllib.request.urlopen(f"{args.base_url}/v1/models", timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}")
        return 1
    for m in data.get("data", []):
        print(m.get("id"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
