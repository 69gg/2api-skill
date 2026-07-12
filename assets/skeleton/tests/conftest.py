"""共享 fixtures：FakeProvider（喂 IREvent 序列）、临时配置/账号目录、测试用 app。"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable

import pytest

from app.config import clear_settings_cache
from app.events import IREvent


class FakeProvider:
    """假上游 provider：按预设 IREvent 序列产出，记录捕获的 prompt/model_id，供 adapter 测试。"""

    def __init__(self, events: Iterable[IREvent]) -> None:
        self._events = list(events)
        self.captured_prompt: str | None = None
        self.captured_model_id: str | None = None

    async def stream(self, prompt: str, model_id: str | None = None, **kw) -> AsyncIterator[IREvent]:
        self.captured_prompt = prompt
        self.captured_model_id = model_id
        for ir in self._events:
            yield ir


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()
    # 避免测试间污染 logging handlers（尤其是写文件的 RotatingFileHandler）
    try:
        from app.logging_setup import reset_logging_for_tests
        reset_logging_for_tests()
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture
def make_account_dir(tmp_path):
    """返回一个工厂：在 tmp_path/account 下创建账号 json。"""

    def _factory(*accounts: dict) -> object:
        d = tmp_path / "account"
        d.mkdir(exist_ok=True)
        for acc in accounts:
            (d / f"{acc['name']}.json").write_text(json.dumps(acc, ensure_ascii=False), encoding="utf-8")
        return d

    return _factory


@pytest.fixture
def app(tmp_path, monkeypatch):
    """构造一个可跑 lifespan 的 FastAPI app：临时 config + 单个 account。"""
    cfg = tmp_path / "config.toml"
    account_dir = tmp_path / "account"
    account_dir.mkdir()
    (account_dir / "main.json").write_text(
        json.dumps({"name": "main", "cookie": "test"}), encoding="utf-8")
    cfg.write_text(
        f'[gateway]\nport = 8088\n\n[registry]\naccount_dir = "{account_dir}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TWOAPI_CONFIG", str(cfg))
    clear_settings_cache()
    from app.main import app as _app  # 延迟 import，使 TWOAPI_CONFIG 生效
    yield _app
    _app.dependency_overrides.clear()


@pytest.fixture
def text_provider():
    """默认 FakeProvider：两段文本 + finish（带 usage）。"""
    from app.events import Usage

    return FakeProvider([
        IREvent(kind="text", text="你好"),
        IREvent(kind="text", text="，世界"),
        IREvent(kind="finish", finish_reason="stop",
                usage_delta=Usage(input_tokens=5, output_tokens=4)),
    ])
