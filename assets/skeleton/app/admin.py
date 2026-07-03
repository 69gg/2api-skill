"""管理后台端点（/admin/*）：账号池查看 / 上传 / 删除 / 重载，独立 ``[admin].auth_key`` 鉴权。

鉴权（二选一）：Header ``Authorization: Bearer <key>`` 或 Query ``?auth_key=<key>``。
``admin_auth_key`` 留空时所有 /admin/* 返回 404（关闭状态，隐藏端点存在）。
"""
from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.account import Account, AccountPool
from app.config import Settings
from app.upstream import get_provider

_bearer = HTTPBearer(auto_error=False)
router = APIRouter(prefix="/admin")


def _get_admin_key(request: Request) -> str:
    return getattr(request.app.state.settings, "admin_auth_key", "")


def verify_admin_key(
    request: Request,
    auth_key: str | None = Query(None, description="管理后台鉴权 key（query 方式）"),
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """校验 admin auth key；未配置时隐藏端点（404），错误时 401。"""
    key = _get_admin_key(request)
    if not key:
        raise HTTPException(status_code=404, detail="admin endpoints disabled")
    provided = ""
    if cred is not None and cred.scheme.lower() == "bearer":
        provided = cred.credentials
    if not provided and auth_key:
        provided = auth_key
    if provided != key:
        raise HTTPException(status_code=401, detail="invalid admin auth key")


def _pool(request: Request) -> AccountPool:
    return request.app.state.pool  # type: ignore[no-any-return]


def _settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def _http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client  # type: ignore[no-any-return]


def _providers(request: Request) -> dict[str, Any]:
    return request.app.state.providers  # type: ignore[no-any-return]


def _sync_provider(providers: dict[str, Any], acc: Account, settings: Settings,
                   http_client: httpx.AsyncClient) -> None:
    """为新增/更新账号构造 UpstreamProvider 并注入 providers 字典。"""
    providers[acc.name] = get_provider(acc, settings, http_client)


def _rebuild_providers(pool: AccountPool, settings: Settings,
                       http_client: httpx.AsyncClient) -> dict[str, Any]:
    providers: dict[str, Any] = {}
    for acc in pool.all():
        _sync_provider(providers, acc, settings, http_client)
    return providers


@router.get("/accounts")
async def list_accounts(request: Request, _: None = Depends(verify_admin_key)) -> dict[str, Any]:
    """列出账号摘要，不暴露凭据等敏感字段。"""
    pool = _pool(request)
    data = [
        {
            "name": a.name,
            "source_email": a.source_email,
            "created_at": a.created_at,
            "disabled": a.disabled,
            "fail_reason": a.fail_reason.value if a.fail_reason else None,
        }
        for a in pool.all()
    ]
    return {"object": "list", "data": data}


@router.get("/accounts/{name}")
async def get_account(request: Request, name: str, _: None = Depends(verify_admin_key)) -> Account:
    """获取单个账号完整信息（含凭据，需 admin 鉴权）。"""
    pool = _pool(request)
    for acc in pool.all():
        if acc.name == name:
            return acc
    raise HTTPException(status_code=404, detail=f"account not found: {name}")


@router.post("/accounts")
async def create_or_update_account(
    request: Request, account: Account, _: None = Depends(verify_admin_key),
) -> Account:
    """上传/新增账号，持久化到 account/<name>.json 并同步内存账号池与 provider 缓存。"""
    pool = _pool(request)
    settings = _settings(request)
    http_client = _http_client(request)
    providers = _providers(request)

    pool.add_or_update(account)
    _sync_provider(providers, account, settings, http_client)
    return account


@router.delete("/accounts/{name}")
async def delete_account(request: Request, name: str, _: None = Depends(verify_admin_key)) -> dict[str, Any]:
    """删除指定账号。"""
    pool = _pool(request)
    providers = _providers(request)
    if not pool.remove(name):
        raise HTTPException(status_code=404, detail=f"account not found: {name}")
    providers.pop(name, None)
    return {"deleted": True, "name": name}


@router.post("/reload")
async def reload_accounts(request: Request, _: None = Depends(verify_admin_key)) -> dict[str, Any]:
    """重新从磁盘加载账号池，并重建 provider 缓存。"""
    pool = _pool(request)
    settings = _settings(request)
    http_client = _http_client(request)
    pool.reload()
    request.app.state.providers = _rebuild_providers(pool, settings, http_client)
    return {"reloaded": True, "count": len(pool.all())}
