"""Token 持久化与并发刷新锁（文件级 `fcntl.flock`）。

适用于 Supabase Auth 等 refresh_token 一次性的场景：多 worker 同时刷新会导致第二个请求使用
已失效的 refresh_token。用 :func:`locked_refresh` 把“读旧 token → 刷新 → 写新 token”包在
文件锁内，避免覆盖与竞态。

Windows 不支持 `fcntl.flock`；骨架目标运行环境为 Linux/Docker，如需跨平台可替换为 SQLite 或
进程级锁。
"""
from __future__ import annotations

import fcntl
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

TokenDict = dict[str, Any]


def load_token(path: str | Path) -> TokenDict:
    """读取 token 文件；文件不存在返回空字典。"""
    p = Path(path)
    if not p.is_file():
        return {}
    with p.open("r", encoding="utf-8") as f:
        # 共享锁即可，读时保证读到完整写完的内容
        fcntl.flock(f.fileno(), fcntl.LOCK_SH)
        try:
            return json.load(f)
        except (json.JSONDecodeError, ValueError):
            return {}


def save_token(path: str | Path, data: TokenDict) -> None:
    """原子写 token 文件（tmp + replace + 排他锁）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(p)


def locked_refresh(
    path: str | Path,
    refresh_fn: Callable[[TokenDict], TokenDict],
    *,
    lock_path: str | Path | None = None,
) -> TokenDict:
    """在文件锁保护下读取旧 token、调用 ``refresh_fn(old)`` 并写入新 token。

    ``refresh_fn`` 内部应执行实际的刷新网络请求，并返回要持久化的新 token dict。
    锁默认使用 ``<token>.lock``，可通过 ``lock_path`` 自定义。
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lock = Path(lock_path) if lock_path is not None else p.with_suffix(p.suffix + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)

    with lock.open("w", encoding="utf-8") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        old = load_token(p)
        new = refresh_fn(old)
        save_token(p, new)
        return new
