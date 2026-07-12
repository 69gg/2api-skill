#!/usr/bin/env python3
"""把 2api-skill 的通用骨架复制到目标项目目录，并按功能开关裁剪。

目录策略（AI 自动选择）：
- 若目标目录为空（仅 .git 除外），直接复制到该目录（默认行为）。
- 若目标目录非空，自动在其下新建 <平台>2api 子目录并复制到子目录。

agent **必须**用本脚本初始化项目，禁止手写/从别处抄骨架。
调用前根据需求与抓包结论填好开关（路由 + 注册机能力 + 是否 init git）。

用法示例：
    python scripts/copy_skeleton.py --platform grok
    python scripts/copy_skeleton.py --platform foo --dest ~/proj --init-git
    python scripts/copy_skeleton.py --platform foo --no-responses --no-messages \\
        --with-registrar --with-email-otp --no-captcha
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


# 标准 .gitignore 条目：复制后 / git_init 后「缺则追加」
REQUIRED_GITIGNORE_LINES: list[str] = [
    "config.toml",
    ".env",
    "account/",
    "accounts/",
    ".venv/",
    "__pycache__/",
    "*.pyc",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    "*.egg-info/",
    "dist/",
    "build/",
    "/tmp/",
    "scripts/probe_out/",
]

# FEATURE 块：支持 HTML 注释 <!-- FEATURE:x --> 与行注释 # FEATURE:x
# 注意：结束标记后只用 [ \t]*\n，避免 \s* 吞掉下一行缩进。
_FEATURE_BLOCK_RE = re.compile(
    r"(?:"
    r"<!--\s*FEATURE:(?P<html_name>[a-z0-9-]+)\s*-->\n?"
    r".*?"
    r"<!--\s*/FEATURE:(?P=html_name)\s*-->[ \t]*\n?"
    r"|"
    r"^[ \t]*#\s*FEATURE:(?P<hash_name>[a-z0-9-]+)[ \t]*\n"
    r".*?"
    r"^[ \t]*#\s*/FEATURE:(?P=hash_name)[ \t]*\n?"
    r")",
    re.DOTALL | re.MULTILINE,
)


def replace_in_tree(dest: Path, replacements: dict[str, str]) -> None:
    for f in dest.rglob("*"):
        if not f.is_file():
            continue
        if ".git" in f.parts:
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


def ensure_gitignore(path: Path) -> None:
    """确保 path 指向的 .gitignore 含标准条目（缺则追加，不覆盖其它规则）。"""
    existing = ""
    if path.is_file():
        existing = path.read_text(encoding="utf-8")
    lines = existing.splitlines()
    have = {ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")}
    to_add = [item for item in REQUIRED_GITIGNORE_LINES if item not in have]
    if not path.is_file():
        path.write_text(
            "# 凭据与本地配置（勿提交）\n"
            + "\n".join(REQUIRED_GITIGNORE_LINES)
            + "\n",
            encoding="utf-8",
        )
        return
    if not to_add:
        return
    suffix = existing if existing.endswith("\n") or existing == "" else existing + "\n"
    suffix += "\n# ensured by 2api-skill copy_skeleton / git_init\n"
    suffix += "\n".join(to_add) + "\n"
    path.write_text(suffix, encoding="utf-8")


def _enabled_set(features: dict[str, bool]) -> set[str]:
    """把布尔 flags 展开为「保留的 FEATURE 块名」集合。

    no-captcha / no-email-otp 是与 captcha / email-otp 互斥的占位块。
    """
    enabled: set[str] = set()
    for name, on in features.items():
        if on:
            enabled.add(name)
    # 互斥占位：关 captcha 时保留 no-captcha 说明块
    if features.get("captcha"):
        enabled.discard("no-captcha")
    else:
        enabled.add("no-captcha")
        enabled.discard("captcha")
    if features.get("email-otp"):
        enabled.discard("no-email-otp")
    else:
        enabled.add("no-email-otp")
        enabled.discard("email-otp")
    return enabled


def strip_feature_blocks(text: str, enabled: set[str]) -> str:
    """删除未启用功能的 FEATURE 块；保留已启用块的内容（去掉标记行）。"""

    def repl(m: re.Match[str]) -> str:
        name = m.group("html_name") or m.group("hash_name") or ""
        if name in enabled:
            # 保留块体：去掉首尾标记行
            body = m.group(0)
            body = re.sub(
                r"<!--\s*FEATURE:" + re.escape(name) + r"\s*-->\n?",
                "",
                body,
                count=1,
            )
            body = re.sub(
                r"<!--\s*/FEATURE:" + re.escape(name) + r"\s*-->\n?",
                "",
                body,
                count=1,
            )
            body = re.sub(
                r"^[ \t]*#\s*FEATURE:" + re.escape(name) + r"\s*\n",
                "",
                body,
                count=1,
                flags=re.MULTILINE,
            )
            body = re.sub(
                r"^[ \t]*#\s*/FEATURE:" + re.escape(name) + r"\s*\n?",
                "",
                body,
                count=1,
                flags=re.MULTILINE,
            )
            return body
        return ""

    prev = None
    out = text
    # 多次扫描：嵌套少见，但避免残留
    while prev != out:
        prev = out
        out = _FEATURE_BLOCK_RE.sub(repl, out)
    # 压缩连续空行
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out


def apply_feature_blocks(dest: Path, enabled: set[str]) -> None:
    """对 dest 内文本文件做 FEATURE 块裁剪。"""
    skip_parts = {".git", ".venv", "__pycache__"}
    for f in dest.rglob("*"):
        if not f.is_file():
            continue
        if any(p in skip_parts for p in f.parts):
            continue
        if f.suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pyc"}:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, ValueError):
            continue
        if "FEATURE:" not in text:
            continue
        new = strip_feature_blocks(text, enabled)
        if new != text:
            f.write_text(new, encoding="utf-8")


def prune_files(dest: Path, features: dict[str, bool]) -> None:
    """按开关删除整文件/目录。"""
    def rm(path: Path) -> None:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.is_file():
            path.unlink()

    if not features.get("chat"):
        rm(dest / "app" / "adapters" / "openai_chat.py")
        rm(dest / "scripts" / "e2e_chat.py")
    if not features.get("responses"):
        rm(dest / "app" / "adapters" / "openai_responses.py")
    if not features.get("messages"):
        rm(dest / "app" / "adapters" / "anthropic_messages.py")
    if not features.get("admin"):
        rm(dest / "app" / "admin.py")
        rm(dest / "tests" / "test_admin.py")
    if not features.get("registrar"):
        rm(dest / "registrar")
        rm(dest / "app" / "auto_register.py")
        rm(dest / "tests" / "test_registrar.py")
        rm(dest / "tests" / "test_auto_register.py")
    else:
        # registrar 开但 captcha 关：仍保留 captcha.py 桩（pipeline 可选用），文档已 N/A
        pass

    # main.py 去掉 registrar 后可能残留未使用的 asyncio
    main_py = dest / "app" / "main.py"
    if main_py.is_file() and not features.get("registrar"):
        text = main_py.read_text(encoding="utf-8")
        if "asyncio." not in text and "import asyncio" in text:
            text = text.replace("import asyncio\n", "")
            main_py.write_text(text, encoding="utf-8")


def write_features_manifest(dest: Path, features: dict[str, Any]) -> None:
    """写入可审计的功能清单（入库）。"""
    path = dest / ".2api-skill-features.json"
    path.write_text(
        json.dumps(features, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_git_init(dest: Path, skill_root: Path, remote: str | None) -> None:
    script = skill_root / "scripts" / "git_init.sh"
    cmd = ["bash", str(script), str(dest)]
    if remote:
        cmd.append(remote)
    subprocess.run(cmd, check=False)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="复制 2api 通用骨架、按功能开关裁剪，并替换占位。",
    )
    ap.add_argument(
        "--dest",
        default=".",
        help="目标父目录（默认当前目录；空则直写，非空则建 <平台>2api 子目录）",
    )
    ap.add_argument("--platform", required=True, help="平台名（如 grok；项目名将为 grok2api）")
    ap.add_argument(
        "--account-dir",
        default="account",
        choices=["account", "accounts"],
        help="账号凭据目录名（默认 account）",
    )

    # 路由（默认全开）
    ap.add_argument("--with-chat", dest="chat", action="store_true", default=True)
    ap.add_argument("--no-chat", dest="chat", action="store_false")
    ap.add_argument("--with-responses", dest="responses", action="store_true", default=True)
    ap.add_argument("--no-responses", dest="responses", action="store_false")
    ap.add_argument("--with-messages", dest="messages", action="store_true", default=True)
    ap.add_argument("--no-messages", dest="messages", action="store_false")
    ap.add_argument("--with-admin", dest="admin", action="store_true", default=True)
    ap.add_argument("--no-admin", dest="admin", action="store_false")

    # 注册机（默认关）
    ap.add_argument(
        "--with-registrar",
        dest="registrar",
        action="store_true",
        default=False,
        help="启用注册机目录与相关文档/配置块",
    )
    ap.add_argument("--no-registrar", dest="registrar", action="store_false")
    ap.add_argument(
        "--with-email-otp",
        dest="email_otp",
        action="store_true",
        default=False,
        help="启用邮件验证码收件（隐含 --with-registrar）",
    )
    ap.add_argument("--no-email-otp", dest="email_otp", action="store_false")
    ap.add_argument(
        "--with-captcha",
        dest="captcha",
        action="store_true",
        default=False,
        help="启用人机验证打码（隐含 --with-registrar）",
    )
    ap.add_argument("--no-captcha", dest="captcha", action="store_false")

    # git
    ap.add_argument(
        "--init-git",
        dest="init_git",
        action="store_true",
        default=False,
        help="复制后自动 git init + 标准 .gitignore + 约定式首提交",
    )
    ap.add_argument("--no-init-git", dest="init_git", action="store_false")
    ap.add_argument(
        "--git-remote",
        default="",
        help="可选 remote URL（仅 --init-git 时生效）",
    )
    return ap


def main() -> int:
    ap = build_arg_parser()
    args = ap.parse_args()

    skill_root = Path(__file__).resolve().parent.parent
    src = skill_root / "assets" / "skeleton"
    if not src.is_dir():
        print(f"找不到骨架目录: {src}", flush=True)
        return 1

    # email-otp / captcha 隐含 registrar
    registrar = bool(args.registrar or args.email_otp or args.captcha)
    email_otp = bool(args.email_otp)
    captcha = bool(args.captcha)
    if (email_otp or captcha) and not args.registrar:
        print("提示: --with-email-otp / --with-captcha 已隐含启用 --with-registrar", flush=True)

    features: dict[str, bool] = {
        "chat": bool(args.chat),
        "responses": bool(args.responses),
        "messages": bool(args.messages),
        "admin": bool(args.admin),
        "registrar": registrar,
        "email-otp": email_otp and registrar,
        "captcha": captcha and registrar,
    }

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

    # 账号目录重命名
    if args.account_dir != "account":
        old, new = dest / "account", dest / args.account_dir
        if old.is_dir():
            old.rename(new)
        cfg = dest / "config.toml.example"
        if cfg.is_file():
            cfg.write_text(
                cfg.read_text(encoding="utf-8").replace(
                    'account_dir = "account"',
                    f'account_dir = "{args.account_dir}"',
                ),
                encoding="utf-8",
            )

    enabled = _enabled_set(features)
    apply_feature_blocks(dest, enabled)
    prune_files(dest, features)
    ensure_gitignore(dest / ".gitignore")

    manifest: dict[str, Any] = {
        "platform": platform,
        "account_dir": args.account_dir,
        "features": features,
        "init_git": bool(args.init_git),
        "git_remote": args.git_remote or None,
        "generator": "2api-skill/scripts/copy_skeleton.py",
    }
    write_features_manifest(dest, manifest)

    if args.init_git:
        run_git_init(dest, skill_root, args.git_remote or None)

    print(f"已生成 {platform}2api 骨架于 {dest}")
    print("功能开关:")
    for k, v in features.items():
        print(f"  {k}: {'on' if v else 'off'}")
    print(f"  init_git: {'yes' if args.init_git else 'no'}")
    print("下一步：")
    print(f"  cd {dest}")
    print("  uv sync --extra dev          # 装依赖（含测试）")
    print("  cp config.toml.example config.toml   # 编辑配置")
    print(f"  cp {args.account_dir}/main.json.example {args.account_dir}/main.json")
    print("  # 实现 app/upstream/（auth/client/parser/models）")
    if not args.init_git:
        print("  # 如需 git：bash <skill>/scripts/git_init.sh <本目录> [远程地址]")
        print("  # 或重新用 copy_skeleton --init-git（勿覆盖已有工作区）")
    print("  uv run uvicorn app.main:app --port 8088")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
