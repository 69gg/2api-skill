"""FastAPI 入口：组装上游 provider + 挂载 OpenAI / Anthropic 兼容路由。"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI

from app.account import AccountPool, FailReason, set_cooldown_policy
from app.adapters.openai_models import router as openai_models_router
# FEATURE:chat
from app.adapters.openai_chat import router as openai_chat_router
# /FEATURE:chat
# FEATURE:responses
from app.adapters.openai_responses import router as openai_responses_router
# /FEATURE:responses
# FEATURE:messages
from app.adapters.anthropic_messages import router as anthropic_router
# /FEATURE:messages
# FEATURE:admin
from app.admin import router as admin_router
# /FEATURE:admin
# FEATURE:registrar
from app.auto_register import start_auto_register, wake_auto_register
# /FEATURE:registrar
from app.config import get_settings
from app.upstream import get_provider


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # 同步可恢复失效的处理策略与冷却时长
    seconds_map: dict[FailReason, float] = {}
    if settings.cooldown_seconds_quota is not None:
        seconds_map[FailReason.QUOTA_EXHAUSTED] = settings.cooldown_seconds_quota
    if settings.cooldown_seconds_cf is not None:
        seconds_map[FailReason.CF_CHALLENGE] = settings.cooldown_seconds_cf
    set_cooldown_policy(
        settings.quota_exhausted_action,
        seconds=settings.cooldown_seconds,
        seconds_map=seconds_map,
    )
    # proxy 未配置时 httpx 直连（proxy=None）
    http_client = httpx.AsyncClient(
        timeout=settings.request_timeout,
        proxy=settings.effective_proxy(),
    )
    # 加载账号池；为每个账号建独立的 UpstreamProvider（共享 http_client）
    pool = AccountPool.load(Path(settings.account_dir))
    providers: dict[str, object] = {}
    for acc in pool.all():
        providers[acc.name] = get_provider(acc, settings, http_client)
    app.state.settings = settings
    app.state.http_client = http_client
    app.state.pool = pool
    app.state.providers = providers
    # FEATURE:registrar
    auto_task = start_auto_register(pool, settings)
    app.state.auto_register_task = auto_task
    if auto_task is not None:
        pool.set_on_changed(wake_auto_register)
    # /FEATURE:registrar
    try:
        yield
    finally:
        # FEATURE:registrar
        if auto_task is not None:
            auto_task.cancel()
            try:
                await auto_task
            except asyncio.CancelledError:
                pass
        # /FEATURE:registrar
        await http_client.aclose()


app = FastAPI(title="{{PLATFORM}}2api", version="0.1.0", lifespan=lifespan)

app.include_router(openai_models_router)
# FEATURE:chat
app.include_router(openai_chat_router)
# /FEATURE:chat
# FEATURE:responses
app.include_router(openai_responses_router)
# /FEATURE:responses
# FEATURE:messages
app.include_router(anthropic_router)
# /FEATURE:messages
# FEATURE:admin
app.include_router(admin_router)
# /FEATURE:admin


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
