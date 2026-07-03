"""账号池测试：round-robin、错误分类换号、冷却、增删改、全失效抛错。"""
from __future__ import annotations

import time

from app.account import (
    _COOLDOWN_SECONDS_MAP,
    Account,
    AccountPool,
    FailReason,
    set_cooldown_policy,
)


def _reset_cooldown_policy() -> None:
    """每个修改冷却策略的测试前后重置为默认。"""
    set_cooldown_policy("cooldown")
    _COOLDOWN_SECONDS_MAP.clear()


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
    _reset_cooldown_policy()
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


def test_name_fallback_to_filename(tmp_path):
    import json
    d = tmp_path / "account"
    d.mkdir()
    (d / "main.json").write_text(json.dumps({"source_email": "a@b.com"}), encoding="utf-8")
    acc = Account.from_file(d / "main.json")
    assert acc.name == "main"
    assert acc.source_email == "a@b.com"


def test_quota_exhausted_disable_policy(tmp_path):
    _reset_cooldown_policy()
    set_cooldown_policy("disable")
    pool, _ = _pool(tmp_path, "a")
    a = pool.all()[0]
    pool.mark_failed(a, FailReason.QUOTA_EXHAUSTED)
    assert a.disabled is True
    assert a.cooldown_until == 0
    # 恢复默认策略，避免影响其他测试
    _reset_cooldown_policy()


def test_cooldown_seconds_per_reason(tmp_path):
    _reset_cooldown_policy()
    pool, _ = _pool(tmp_path, "a")
    a = pool.all()[0]
    now = time.time()
    set_cooldown_policy(
        "cooldown",
        seconds_map={
            FailReason.QUOTA_EXHAUSTED: 120.0,
            FailReason.CF_CHALLENGE: 30.0,
        },
    )
    pool.mark_failed(a, FailReason.QUOTA_EXHAUSTED)
    assert a.disabled is False
    assert 119.0 <= a.cooldown_until - now <= 121.0
    _reset_cooldown_policy()
