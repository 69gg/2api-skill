#!/usr/bin/env python3
"""把抓到的模型列表生成 app/upstream/models.py 的 MODEL_CATALOG 代码（杜绝硬编码）。

实地用 chrome-devtools 抓取（/models 响应、前端模型选择按钮的 data-*、或 JS bundle）后喂本脚本。

用法：
    # 本地 JSON 文件
    python scripts/probe_catalog.py --source models.json --platform grok > app/upstream/models_catalog.py

    # 直接请求上游 API（返回 JSON 数组或嵌套对象）
    python scripts/probe_catalog.py --source https://api.example.com/v1/models --source-type api

    # 从前端 JS bundle 提取 models/modelList 数组
    python scripts/probe_catalog.py --source dist/main.js --source-type bundle

source JSON：模型数组，元素可含 id / name / owner / value（或 upstream_id）。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import httpx

# 常见嵌套 key，normalize 会逐层探测
_MODEL_CONTAINER_KEYS = ("modelList", "models", "model_list", "availableModels", "data", "items", "results", "list")


def _is_model_list(items: Any) -> bool:
    """判断 items 是否像模型数组。"""
    if not isinstance(items, list) or not items:
        return False
    return all(
        isinstance(x, dict) and (x.get("id") or x.get("name") or x.get("value") or x.get("model"))
        for x in items
    )


def _find_first_model_list(data: Any) -> list[Any]:
    """递归查找第一个模型数组（支持 dict 嵌套）。"""
    if _is_model_list(data):
        return data
    if isinstance(data, dict):
        # 优先按常见 key 名取，避免误把外层 list 当模型
        for key in _MODEL_CONTAINER_KEYS:
            candidate = data.get(key)
            found = _find_first_model_list(candidate)
            if found:
                return found
        # 再递归其他 value
        for v in data.values():
            found = _find_first_model_list(v)
            if found:
                return found
    if isinstance(data, list):
        for item in data:
            found = _find_first_model_list(item)
            if found:
                return found
    return []


def normalize(data: list[Any], platform: str) -> list[dict[str, Any]]:
    """把原始模型数组归一化成 MODEL_CATALOG 条目。"""
    data = _find_first_model_list(data)
    out: list[dict[str, Any]] = []
    for m in data:
        if not isinstance(m, dict):
            continue
        mid = m.get("id") or m.get("value") or m.get("name") or m.get("model")
        name = m.get("name") or m.get("label") or m.get("display_name") or mid
        if not mid:
            continue
        out.append({
            "id": str(mid),
            "name": str(name),
            "owner": str(m.get("owner") or platform),
            "upstream_id": m.get("upstream_id") or m.get("value") or m.get("model") or mid,
        })
    return out


def extract_from_bundle(text: str) -> list[dict[str, Any]]:
    """从 JS bundle 文本中提取 ``models: [...]`` / ``modelList: [...]`` 等数组。"""
    for key in ("modelList", "models", "model_list", "availableModels"):
        for match in re.finditer(re.escape(key) + r"\s*:", text):
            idx = match.end()
            try:
                while idx < len(text) and text[idx].isspace():
                    idx += 1
                if idx >= len(text) or text[idx] != "[":
                    continue
                data, _ = json.JSONDecoder().raw_decode(text, idx)
                if isinstance(data, list):
                    return data
            except (json.JSONDecodeError, IndexError):
                continue
    return []


def fetch_source(source: str) -> str:
    """若 source 是 URL，用 httpx 获取内容；否则按文件读取。"""
    if source.startswith(("http://", "https://")):
        r = httpx.get(source, timeout=30)
        r.raise_for_status()
        return r.text
    return Path(source).read_text(encoding="utf-8")


def detect_source_type(source: str) -> str:
    """按 source 特征推断类型。"""
    if source.startswith(("http://", "https://")):
        return "api"
    ext = Path(source).suffix.lower()
    if ext in (".js", ".mjs", ".ts", ".bundle"):
        return "bundle"
    return "json"


def render(catalog: list[dict[str, Any]]) -> str:
    lines: list[str] = ["MODEL_CATALOG: list[dict[str, Any]] = ["]
    for m in catalog:
        lines.append(
            f'    {{"id": {json.dumps(m["id"])}, "name": {json.dumps(m["name"])}, '
            f'"owner": {json.dumps(m["owner"])}, "upstream_id": {json.dumps(m["upstream_id"])}}},'
        )
    lines.append("]")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="模型数据 → MODEL_CATALOG 代码")
    ap.add_argument("--source", required=True, help="模型数据来源：文件路径或 URL")
    ap.add_argument("--source-type", default="auto", choices=["auto", "json", "api", "bundle"],
                    help="数据来源类型（auto 自动推断）")
    ap.add_argument("--platform", default="unknown", help="默认 owner")
    args = ap.parse_args()

    source_type = args.source_type
    if source_type == "auto":
        source_type = detect_source_type(args.source)

    raw_text = fetch_source(args.source)

    if source_type == "bundle":
        data = extract_from_bundle(raw_text)
    else:
        # json / api 都按 JSON 解析
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            print(f"# JSON 解析失败: {exc}", flush=True)
            return 1

    catalog = normalize(data, args.platform)
    if not catalog:
        print("# 未识别到模型，请检查 source 结构或尝试 --source-type", flush=True)
        return 1
    print("# 由 scripts/probe_catalog.py 生成；粘进 app/upstream/models.py 替换占位 MODEL_CATALOG。")
    print(render(catalog))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
