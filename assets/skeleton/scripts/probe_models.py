"""抓包探针：用真实账号凭据跑通认证链 + 发送对话，打印上游响应结构（逆向的起点）。

复制本文件到生成项目后，按目标站填充认证与请求逻辑（参考 app/upstream/ 实现）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="上游探针：抓包确认响应结构")
    ap.add_argument("--account", default="account/main.json", help="账号凭据文件")
    args = ap.parse_args()
    acc = json.loads(Path(args.account).read_text(encoding="utf-8"))
    print(f"账号: {acc.get('name')}")
    print(f"凭据字段: {[k for k in acc if k not in ('name', 'source_email', 'created_at', 'disabled', 'fail_reason', 'cooldown_until')]}")
    print("TODO: 按 app/upstream/ 实现，用真实账号跑通认证链 + 发送一条对话，打印上游响应结构。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
