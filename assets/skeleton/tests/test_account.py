"""账号池测试：round-robin、错误分类换号、冷却、增删改、全失效抛错。"""
from __future__ import annotations

import time

from app.account import Account, AccountPool, FailReason


def _pool(tmp_path, *names):
    d = tmp_path / "account"
    d.mkdir(exist_ok=True)
    import json
    for n in names:
        (d / f"{n}.json").write_text(json.dumps({"name": n}), encoding="utf-8")
    return AccountPool.load(d), d


def test_round_robin(tmp_path):
    pool, _ = _pool(tmp_path, "a", "b", "c")
    seq = [pool.next().name for _ in range(7)]
    assert seq == ["a", "b", "c", "a", "b", "c", "a"]


def test_mark_failed_dead_disables(tmp_path):
    pool, d = _pool(tmp_path, "a", "b")
    a = next(x for x in pool.all() if x.name == "a")
    pool.mark_failed(a, FailReason.AUTH_FAILED)
    assert a.disabled is True
    assert a.fail_reason == FailReason.AUTH_FAILED
    assert {x.name for x in pool.all()} == {"a", "b"}
    # a 被 disabled，只剩 b
    assert all(pool.next().name == "b" for _ in range(3))


def test_mark_failed_quota_cooldown(tmp_path, monkeypatch):
    pool, _ = _pool(tmp_path, "a", "b")
    a = next(x for x in pool.all() if x.name == "a")
    pool.mark_failed(a, FailReason.QUOTA_EXHAUSTED)
    assert a.disabled is False
    assert a.cooldown_until > time.time()
    # a 冷却中，只剩 b
    assert all(pool.next().name == "b" for _ in range(3))
    # 冷却到期后恢复
    monkeypatch.setattr(time, "time", lambda: a.cooldown_until + 1)
    assert pool.next().name in {"a", "b"}


def test_add_remove_reload(tmp_path):
    pool, d = _pool(tmp_path, "a")
    pool.add_or_update(Account(name="b"))
    assert {x.name for x in pool.all()} == {"a", "b"}
    assert pool.remove("a") is True
    assert {x.name for x in pool.all()} == {"b"}
    pool.reload()
    assert {x.name for x in pool.all()} == {"b"}


def test_all_failed_raises(tmp_path):
    pool, _ = _pool(tmp_path, "a")
    a = pool.all()[0]
    pool.mark_failed(a, FailReason.BANNED)
    import pytest
    with pytest.raises(RuntimeError):
        pool.next()


def test_extra_fields_allowed(tmp_path):
    import json
    d = tmp_path / "account"
    d.mkdir()
    (d / "x.json").write_text(json.dumps({"name": "x", "cookie": "ck", "project_id": "p"}), encoding="utf-8")
    acc = Account.from_file(d / "x.json")
    assert acc.cookie == "ck"  # type: ignore[attr-defined]
    assert acc.project_id == "p"  # type: ignore[attr-defined]
