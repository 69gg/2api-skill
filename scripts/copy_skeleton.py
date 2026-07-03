#!/usr/bin/env python3
"""把 2api-skill 的通用骨架复制到目标项目目录，并替换占位。

用法：
    python scripts/copy_skeleton.py --dest ~/proj/grok2api --platform grok
    python scripts/copy_skeleton.py --dest ./foo2api --platform foo --account-dir accounts
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def replace_in_tree(dest: Path, replacements: dict[str, str]) -> None:
    for f in dest.rglob("*"):
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, ValueError):
            continue
        changed = text
        for k, v in replacements.items():
            changed = changed.replace(k, v)
        if changed != text:
            f.write_text(changed, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="复制 2api 通用骨架并替换占位。")
    ap.add_argument("--dest", required=True, help="目标项目目录")
    ap.add_argument("--platform", required=True, help="平台名（如 grok；项目名将为 grok2api）")
    ap.add_argument("--account-dir", default="account", choices=["account", "accounts"],
                    help="账号凭据目录名（默认 account）")
    args = ap.parse_args()

    skill_root = Path(__file__).resolve().parent.parent
    src = skill_root / "assets" / "skeleton"
    dest = Path(args.dest).resolve()
    if not src.is_dir():
        print(f"找不到骨架目录: {src}", flush=True)
        return 1
    if dest.exists() and any(dest.iterdir()):
        print(f"目标目录非空，已中止（避免覆盖）: {dest}", flush=True)
        return 1

    shutil.copytree(src, dest)
    platform = args.platform
    replacements: dict[str, str] = {
        "{{PROJECT_NAME}}": f"{platform}2api",
        "{{Platform}}": platform.capitalize(),
        "{{PLATFORM}}": platform,
        "{{platform}}": platform,
    }
    replace_in_tree(dest, replacements)

    # 可选的账号目录重命名（skeleton 默认 account/）
    if args.account_dir != "account":
        old, new = dest / "account", dest / args.account_dir
        if old.is_dir():
            old.rename(new)
        cfg = dest / "config.toml.example"
        if cfg.is_file():
            cfg.write_text(cfg.read_text(encoding="utf-8").replace(
                'account_dir = "account"', f'account_dir = "{args.account_dir}"'), encoding="utf-8")

    print(f"已生成 {platform}2api 骨架于 {dest}")
    print("下一步：")
    print(f"  cd {dest}")
    print("  uv sync --extra dev          # 装依赖（含测试）")
    print("  cp config.toml.example config.toml   # 编辑配置")
    print("  # 把账号凭据放到 account/main.json")
    print("  # 实现 app/upstream/（auth/client/parser/models），见 references/upstream-adapters.md")
    print("  uv run uvicorn app.main:app --port 8088")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
