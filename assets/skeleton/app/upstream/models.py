"""ModelRegistry 占位：模型目录。

⚠️ 模型列表**必须实地探测，勿硬编码**！用 ``scripts/probe_catalog.py`` 从上游前端/UI
抓取后填入 :data:`MODEL_CATALOG`（参考 references/upstream-adapters.md 的「模型探测」）。
"""
from __future__ import annotations

import re
from typing import Any

from app.upstream.base import ModelRegistry

DEFAULT_MODEL = "gpt-4o"

# TODO: 用 scripts/probe_catalog.py 探测后填入（字段：id / name / owner / upstream_id）。
MODEL_CATALOG: list[dict[str, Any]] = [
    {"id": DEFAULT_MODEL, "name": "Default", "owner": "unknown", "upstream_id": None},
]

_BY_KEY: dict[str, dict[str, Any]] = {}
for _m in MODEL_CATALOG:
    _BY_KEY[_m["id"]] = _m
    _BY_KEY[_m["name"].lower()] = _m


class DefaultModelRegistry(ModelRegistry):
    def catalog(self) -> list[dict[str, Any]]:
        return list(MODEL_CATALOG)

    def normalize(self, model: str | None) -> str:
        """客户端传入的 model → catalog id；空或未知 → 默认。匹配：精确 id > 显示名(小写) > 模糊。"""
        if not model:
            return DEFAULT_MODEL
        if model in _BY_KEY:
            return _BY_KEY[model]["id"]
        low = model.lower()
        if low in _BY_KEY:
            return _BY_KEY[low]["id"]
        norm = re.sub(r"[^a-z0-9]", "", low)
        for m in MODEL_CATALOG:
            if (re.sub(r"[^a-z0-9]", "", m["id"]) == norm
                    or re.sub(r"[^a-z0-9]", "", m["name"].lower()) == norm):
                return m["id"]
        return DEFAULT_MODEL

    def upstream_id_for(self, model_id: str) -> str | None:
        m = _BY_KEY.get(model_id)
        return m["upstream_id"] if m else None
