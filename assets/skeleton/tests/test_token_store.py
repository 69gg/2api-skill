"""token_store 测试：文件锁读写与 locked_refresh。"""
from __future__ import annotations

from app.upstream.token_store import load_token, locked_refresh, save_token


def test_save_and_load_token(tmp_path):
    p = tmp_path / "token.json"
    save_token(p, {"access_token": "a", "refresh_token": "b"})
    assert load_token(p) == {"access_token": "a", "refresh_token": "b"}


def test_load_missing_returns_empty(tmp_path):
    assert load_token(tmp_path / "not_exist.json") == {}


def test_locked_refresh_writes_new_token(tmp_path):
    p = tmp_path / "token.json"
    save_token(p, {"access_token": "old", "refresh_token": "old_rt"})

    def refresh(old):
        return {"access_token": "new", "refresh_token": old.get("refresh_token", "") + "_used"}

    new = locked_refresh(p, refresh)
    assert new["access_token"] == "new"
    assert load_token(p) == new


def test_locked_refresh_serializes_concurrent_refresh(tmp_path):
    """模拟并发刷新：locked_refresh 保证 refresh_fn 串行执行。"""
    import threading

    p = tmp_path / "token.json"
    save_token(p, {"counter": 0})
    calls = []

    def refresh(old):
        calls.append(1)
        return {"counter": old.get("counter", 0) + 1}

    threads = [threading.Thread(target=locked_refresh, args=(p, refresh)) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 5 次刷新都应成功，结果 counter 为 5
    assert load_token(p)["counter"] == 5
