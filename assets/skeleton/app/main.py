"""FastAPI 入口：组装上游 provider + 挂载 OpenAI / Anthropic 兼容路由。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI

from app.account import AccountPool
from app.adapters.anthropic_messages import router as anthropic_router
from app.adapters.openai_chat import router as openai_chat_router
from app.adapters.openai_models import router as openai_models_router
from app.adapters.openai_responses import router as openai_responses_router
from app.admin import router as admin_router
from app.config import get_settings
from app.upstream import get_provider


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    http_client = httpx.AsyncClient(timeout=settings.request_timeout)
    # 加载账号池；为每个账号建独立的 UpstreamProvider（共享 http_client）
    pool = AccountPool.load(Path(settings.account_dir))
    providers: dict[str, object] = {}
    for acc in pool.all():
        providers[acc.name] = get_provider(acc, settings, http_client)
    app.state.settings = settings
    app.state.http_client = http_client
    app.state.pool = pool
    app.state.providers = providers
    try:
        yield
    finally:
        await http_client.aclose()


app = FastAPI(title="{{PLATFORM}}2api", version="0.1.0", lifespan=lifespan)

app.include_router(openai_models_router)
app.include_router(openai_chat_router)
app.include_router(openai_responses_router)
app.include_router(anthropic_router)
app.include_router(admin_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
