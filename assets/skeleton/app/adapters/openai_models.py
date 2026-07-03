"""OpenAI /v1/models 兼容接口（模型列表来自 upstream registry，实地探测不硬编码）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.adapters import supported_models
from app.deps import verify_api_key

router = APIRouter()


@router.get("/v1/models")
async def list_models(_: None = Depends(verify_api_key)) -> dict:
    return {"object": "list", "data": supported_models()}
