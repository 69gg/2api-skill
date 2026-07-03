#!/usr/bin/env python3
"""把 2api-skill 的通用骨架复制到目标项目目录，并替换占位。

目录策略（AI 自动选择）：
- 若目标目录为空（仅 .git 除外），直接复制到该目录（默认行为）。
- 若目标目录非空，自动在其下新建 <平台>2api 子目录并复制到子目录。

用法：
    python scripts/copy_skeleton.py --platform grok              # 当前目录为空则直接复制
    python scripts/copy_skeleton.py --platform grok --dest ./    # 同上，显式指定当前目录
    python scripts/copy_skeleton.py --platform foo --dest ~/proj # 非空则在 ~/proj/foo2api 生成
    python scripts/copy_skeleton.py --platform foo --dest ./foo2api --account-dir accounts
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


def is_empty_except_git(path: Path) -> bool:
    """目标目录允许只包含 .git；其他任意文件/目录均视为非空。"""
    if not path.exists():
        return True
    for child in path.iterdir():
        if child.name == ".git":
            continue
        return False
    return True


def copy_items(src: Path, dest: Path) -> None:
    """将 src 下的顶层文件/目录逐个复制到 dest，避免整体替换目标文件夹。"""
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def resolve_dest(dest: Path, platform: str) -> Path:
    """按「空则直接复制、非空则新建 <平台>2api 子目录」策略解析目标目录。"""
    dest = dest.resolve()
    if is_empty_except_git(dest):
        return dest
    sub = dest / f"{platform}2api"
    if not is_empty_except_git(sub):
        print(f"目标目录及其 {sub.name} 子目录均非空，已中止（避免覆盖）: {dest}", flush=True)
        raise SystemExit(1)
    return sub


def main() -> int:
    ap = argparse.ArgumentParser(description="复制 2api 通用骨架并替换占位。")
    ap.add_argument("--dest", default=".", help="目标父目录（默认当前目录；空则直写，非空则建 <平台>2api 子目录）")
    ap.add_argument("--platform", required=True, help="平台名（如 grok；项目名将为 grok2api）")
    ap.add_argument("--account-dir", default="account", choices=["account", "accounts"],
                    help="账号凭据目录名（默认 account）")
    args = ap.parse_args()

    skill_root = Path(__file__).resolve().parent.parent
    src = skill_root / "assets" / "skeleton"
    if not src.is_dir():
        print(f"找不到骨架目录: {src}", flush=True)
        return 1

    platform = args.platform
    dest = resolve_dest(Path(args.dest), platform)
    copy_items(src, dest)
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
    print("  cp account/main.json.example account/main.json   # 账号凭据模板")
    print("  # account/<name>.json 必填字段：name、source_email、created_at")
    print("  # 实现 app/upstream/（auth/client/parser/models），见 references/upstream-adapters.md")
    print("  # 如需 git，运行：bash scripts/git_init.sh [远程仓库地址]")
    print("  uv run uvicorn app.main:app --port 8088")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
