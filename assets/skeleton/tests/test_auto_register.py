"""自动补足账号任务测试。"""
from __future__ import annotations

import pytest

from app.account import AccountPool
from app.auto_register import start_auto_register
from app.config import Settings


async def test_auto_register_disabled_by_default(tmp_path):
    d = tmp_path / "account"
    d.mkdir()
    (d / "main.json").write_text('{"name":"main"}', encoding="utf-8")
    pool = AccountPool.load(d)
    settings = Settings(target_account_count=0)
    assert start_auto_register(pool, settings) is None


async def test_auto_register_starts_when_target_set(tmp_path):
    import asyncio

    d = tmp_path / "account"
    d.mkdir()
    (d / "main.json").write_text('{"name":"main"}', encoding="utf-8")
    pool = AccountPool.load(d)
    settings = Settings(target_account_count=2, auto_register_interval=300.0)
    task = start_auto_register(pool, settings)
    assert task is not None
    assert task.get_name() == "auto_register"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_auto_register_wakes_on_mark_failed(tmp_path):
    import asyncio

    from app.account import FailReason

    d = tmp_path / "account"
    d.mkdir()
    (d / "main.json").write_text('{"name":"main"}', encoding="utf-8")
    pool = AccountPool.load(d)
    settings = Settings(target_account_count=2, auto_register_interval=300.0)
    task = start_auto_register(pool, settings)
    assert task is not None

    event = asyncio.Event()
    pool.set_on_changed(event.set)
    account = pool.all()[0]
    pool.mark_failed(account, FailReason.AUTH_FAILED)
    await asyncio.sleep(0)  # 让 call_soon_threadsafe 的回调执行
    assert event.is_set()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
