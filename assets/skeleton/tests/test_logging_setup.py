"""logging_setup：文件轮转开关与配置。"""
from __future__ import annotations

import logging
from pathlib import Path

from app.config import Settings
from app.logging_setup import reset_logging_for_tests, setup_logging


def test_setup_logging_writes_file_when_enabled(tmp_path: Path) -> None:
    reset_logging_for_tests()
    settings = Settings(
        log_enabled=True,
        log_dir=str(tmp_path / "logs"),
        log_filename="test.log",
        log_level="INFO",
        log_max_bytes=1024 * 1024,
        log_backup_count=2,
    )
    setup_logging(settings)
    log = logging.getLogger("app.http_log")
    log.info("hello-from-test")
    # 强制 flush handlers
    for h in logging.getLogger().handlers:
        h.flush()
    path = tmp_path / "logs" / "test.log"
    assert path.is_file()
    content = path.read_text(encoding="utf-8")
    assert "hello-from-test" in content
    reset_logging_for_tests()


def test_setup_logging_no_file_when_disabled(tmp_path: Path) -> None:
    reset_logging_for_tests()
    settings = Settings(
        log_enabled=False,
        log_dir=str(tmp_path / "logs"),
        log_filename="should-not-exist.log",
    )
    setup_logging(settings)
    logging.getLogger("app").info("console-only")
    assert not (tmp_path / "logs" / "should-not-exist.log").exists()
    reset_logging_for_tests()
