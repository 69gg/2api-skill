"""服务运行时自动补足账号到目标数量。

在 ``app/main.py`` 的 lifespan 中启动。配置项（``[registry]`` 段）：
- ``target_account_count``: 目标可用账号数（0=关闭自动补足）
- ``auto_register_interval``: 检查间隔（秒，默认 300）
- ``auto_register_workers``: 单次并发注册数（默认 1）
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.account import AccountPool
from app.config import Settings

logger = logging.getLogger(__name__)

# 模块级唤醒事件：账号状态变化时触发 auto_register 立即检查
_wake_event: asyncio.Event | None = None


def _ensure_wake_event() -> asyncio.Event:
    global _wake_event
    if _wake_event is None:
        _wake_event = asyncio.Event()
    return _wake_event


def wake_auto_register() -> None:
    """触发自动补账号任务立即检查（线程安全；无运行事件循环时忽略）。"""
    event = _wake_event
    if event is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.call_soon_threadsafe(event.set)


def start_auto_register(
    pool: AccountPool, settings: Settings
) -> asyncio.Task[Any] | None:
    """若配置 ``target_account_count > 0``，启动后台任务自动补足账号。"""
    target = getattr(settings, "target_account_count", 0)
    if target <= 0:
        return None
    interval = getattr(settings, "auto_register_interval", 300.0)
    workers = max(1, getattr(settings, "auto_register_workers", 1))
    _ensure_wake_event()
    return asyncio.create_task(
        _auto_register_loop(pool, target, interval, workers), name="auto_register"
    )


async def _auto_register_loop(
    pool: AccountPool, target: int, interval: float, workers: int
) -> None:
    """定期检查并补足账号；支持被 wake_auto_register 立即唤醒。注册机相关导入延迟到函数内。"""
    # 延迟导入：app 不应在模块顶层依赖 registrar
    from registrar.http_client import HttpClient
    from registrar.models import load_registrar_config
    from registrar.pipeline import register_one

    event = _ensure_wake_event()
    while True:
        try:
            available = pool.available_count()
            if available >= target:
                logger.debug("auto_register: %d/%d accounts available, skip", available, target)
            else:
                need = target - available
                logger.info("auto_register: %d/%d accounts, registering %d", available, target, need)
                cfg = load_registrar_config()
                http = HttpClient()
                semaphore = asyncio.Semaphore(workers)

                async def _register_one() -> dict[str, Any] | BaseException:
                    async with semaphore:
                        try:
                            return await asyncio.to_thread(register_one, cfg, http)
                        except BaseException as exc:  # noqa: BLE001
                            return exc

                results = await asyncio.gather(*(_register_one() for _ in range(need)))
                success = sum(1 for r in results if isinstance(r, dict))
                failures = [r for r in results if isinstance(r, BaseException)]
                for exc in failures:
                    logger.warning("auto_register failure: %s", exc)
                if success:
                    logger.info("auto_register: %d new account(s), reloading pool", success)
                    pool.reload()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("auto_register loop error")
        # 等待 interval，或被 wake_auto_register 立即唤醒
        event.clear()
        try:
            await asyncio.wait_for(event.wait(), timeout=interval)
        except TimeoutError:
            pass
