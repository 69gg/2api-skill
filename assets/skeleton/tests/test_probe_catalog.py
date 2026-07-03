"""probe_catalog 测试：JSON API 响应与 JS bundle 提取。"""
from __future__ import annotations

from scripts.probe_catalog import extract_from_bundle, normalize, render


def test_normalize_flat_array():
    data = [
        {"id": "gpt-4o", "name": "GPT-4o", "upstream_id": "gpt-4o-123"},
        {"name": "GPT-4", "value": "gpt-4"},
    ]
    catalog = normalize(data, "test")
    assert catalog[0] == {"id": "gpt-4o", "name": "GPT-4o", "owner": "test", "upstream_id": "gpt-4o-123"}
    assert catalog[1]["id"] == "gpt-4"
    assert catalog[1]["upstream_id"] == "gpt-4"


def test_normalize_nested_api_response():
    data = {
        "data": {
            "models": [
                {"id": "model-a", "name": "Model A"},
                {"id": "model-b", "name": "Model B"},
            ]
        }
    }
    catalog = normalize(data, "nested")
    assert len(catalog) == 2
    assert catalog[0]["id"] == "model-a"


def test_extract_from_bundle():
    bundle = """
    const CONFIG = { modelList: [{"id":"gpt-4o","name":"GPT-4o"}, {"id":"claude","name":"Claude"}] };
    const OTHER = { models: [{"id":"old","name":"Old"}] };
    """
    models = extract_from_bundle(bundle)
    assert len(models) == 2
    assert models[0]["id"] == "gpt-4o"


def test_render():
    catalog = [{"id": "x", "name": "X", "owner": "o", "upstream_id": "u"}]
    out = render(catalog)
    assert "MODEL_CATALOG" in out
    assert '"x"' in out
