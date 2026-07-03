#!/usr/bin/env python3
"""把抓到的模型列表生成 app/upstream/models.py 的 MODEL_CATALOG 代码（杜绝硬编码）。

实地用 chrome-devtools 抓取（/models 响应、或前端模型选择按钮的 data-*）后喂本脚本。

用法：
    python scripts/probe_catalog.py --source models.json --platform grok > app/upstream/models_catalog.py

source JSON：模型数组，元素可含 id / name / owner / value（或 upstream_id）。
"""
from __future__ import annotations

import argparse
import json
from typing import Any


def normalize(data: list[Any], platform: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in data:
        if not isinstance(m, dict):
            continue
        mid = m.get("id") or m.get("value") or m.get("name")
        name = m.get("name") or m.get("label") or mid
        if not mid:
            continue
        out.append({
            "id": str(mid),
            "name": str(name),
            "owner": str(m.get("owner") or platform),
            "upstream_id": m.get("upstream_id") or m.get("value") or mid,
        })
    return out


def render(catalog: list[dict[str, Any]]) -> str:
    lines: list[str] = ["MODEL_CATALOG: list[dict[str, Any]] = ["]
    for m in catalog:
        lines.append(
            f'    {{"id": {m["id"]!r}, "name": {m["name"]!r}, '
            f'"owner": {m["owner"]!r}, "upstream_id": {m["upstream_id"]!r}}},'
        )
    lines.append("]")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="模型数据 → MODEL_CATALOG 代码")
    ap.add_argument("--source", required=True, help="模型数据 JSON 文件")
    ap.add_argument("--platform", default="unknown", help="默认 owner")
    args = ap.parse_args()
    with open(args.source, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("data") or data.get("models") or []
    catalog = normalize(data, args.platform)
    if not catalog:
        print("# 未识别到模型，请检查 source JSON 结构", flush=True)
        return 1
    print("# 由 scripts/probe_catalog.py 生成；粘进 app/upstream/models.py 替换占位 MODEL_CATALOG。")
    print(render(catalog))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
