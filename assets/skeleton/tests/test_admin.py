"""admin 测试：留空关闭(404)、错 key(401)、CRUD + reload、敏感字段隐藏。"""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_admin_disabled_without_key(app):
    with TestClient(app) as client:
        assert client.get("/admin/accounts").status_code == 404  # admin_auth_key 默认空 → 关闭


def test_admin_crud(app):
    with TestClient(app) as client:
        app.state.settings.admin_auth_key = "adm"
        h = {"Authorization": "Bearer adm"}

        # list（main 账号已在 conftest app fixture 创建）
        r = client.get("/admin/accounts", headers=h)
        assert r.status_code == 200
        names = [a["name"] for a in r.json()["data"]]
        assert "main" in names
        # list 摘要不暴露凭据字段
        assert "cookie" not in r.json()["data"][0]

        # create
        r2 = client.post("/admin/accounts", headers=h, json={"name": "new", "cookie": "x"})
        assert r2.status_code == 200
        assert client.get("/admin/accounts", headers=h).json()["data"][-1]["name"] != ""

        # get（含凭据）
        r3 = client.get("/admin/accounts/new", headers=h)
        assert r3.status_code == 200
        assert r3.json()["name"] == "new"

        # delete
        assert client.delete("/admin/accounts/new", headers=h).status_code == 200
        assert client.get("/admin/accounts/new", headers=h).status_code == 404

        # reload
        rr = client.post("/admin/reload", headers=h)
        assert rr.status_code == 200
        assert rr.json()["reloaded"] is True


def test_admin_wrong_key(app):
    with TestClient(app) as client:
        app.state.settings.admin_auth_key = "adm"
        assert client.get("/admin/accounts",
                          headers={"Authorization": "Bearer wrong"}).status_code == 401
        # query 方式也支持
        assert client.get("/admin/accounts?auth_key=adm").status_code == 200
