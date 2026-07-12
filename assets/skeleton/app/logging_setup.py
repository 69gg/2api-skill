"""统一日志初始化：控制台 + 可选 ``logs/`` 轮转文件。

由 :func:`setup_logging` 在 lifespan 启动时调用。``[logging]`` 段控制：
是否落盘、目录、文件名、级别、单文件大小、保留份数。
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_FILE_HANDLER_NAME = "twoapi_rotating_file"
_CONSOLE_HANDLER_NAME = "twoapi_console"
_CONFIGURED = False


def setup_logging(settings: Any | None = None) -> None:
    """幂等配置 root logger。

    - 始终挂控制台 handler（uvicorn 已有则复用 root，只设级别）。
    - ``settings.log_enabled`` 为真时，额外挂 ``RotatingFileHandler`` 到
      ``{log_dir}/{log_filename}``。
    """
    global _CONFIGURED
    level_name = "INFO"
    log_enabled = True
    log_dir = "logs"
    log_filename = "gateway.log"
    max_bytes = 10 * 1024 * 1024
    backup_count = 5

    if settings is not None:
        level_name = (getattr(settings, "log_level", None) or "INFO").upper()
        log_enabled = bool(getattr(settings, "log_enabled", True))
        log_dir = str(getattr(settings, "log_dir", None) or "logs")
        log_filename = str(getattr(settings, "log_filename", None) or "gateway.log")
        max_bytes = int(getattr(settings, "log_max_bytes", None) or max_bytes)
        backup_count = int(getattr(settings, "log_backup_count", None) or backup_count)

    level = getattr(logging, level_name, logging.INFO)
    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)

    # 控制台：仅当 root 尚无 StreamHandler 时添加，避免与 uvicorn 重复刷屏
    has_console = any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        for h in root.handlers
    )
    if not has_console:
        console = logging.StreamHandler(sys.stderr)
        console.set_name(_CONSOLE_HANDLER_NAME)
        console.setFormatter(fmt)
        console.setLevel(level)
        root.addHandler(console)

    # 文件：先移除旧的同名 handler，再按 enabled 决定是否挂上
    for h in list(root.handlers):
        if getattr(h, "name", None) == _FILE_HANDLER_NAME:
            root.removeHandler(h)
            h.close()

    if log_enabled:
        path = Path(log_dir)
        path.mkdir(parents=True, exist_ok=True)
        file_path = path / log_filename
        fh = RotatingFileHandler(
            file_path,
            maxBytes=max(1024, max_bytes),
            backupCount=max(0, backup_count),
            encoding="utf-8",
        )
        fh.set_name(_FILE_HANDLER_NAME)
        fh.setFormatter(fmt)
        fh.setLevel(level)
        root.addHandler(fh)

    for name in (
        "app",
        "app.upstream",
        "app.adapters",
        "app.deps",
        "app.orchestrator",
        "app.http_log",
        "app.auto_register",
    ):
        logging.getLogger(name).setLevel(level)

    _CONFIGURED = True


def reset_logging_for_tests() -> None:
    """测试用：移除本模块添加的 handler，重置状态。"""
    global _CONFIGURED
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "name", None) in (_FILE_HANDLER_NAME, _CONSOLE_HANDLER_NAME):
            root.removeHandler(h)
            h.close()
    _CONFIGURED = False
