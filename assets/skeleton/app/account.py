"""账号凭据与账号池（通用，支持错误分类换号与冷却）。

每个账号一份 ``account/<name>.json``，启动时全量加载；请求时 round-robin 轮换可用子集。
失效按 :class:`FailReason` 分类：不可恢复（认证失败/封号）→ disabled 永久剔除；
可恢复（额度耗尽/人机验证）→ 冷却一段时间后自动恢复。
账号扩展字段（目标网站专属凭据：cookie/token/project_id 等）通过 ``extra=allow`` 容纳。
"""
from __future__ import annotations

import fcntl
import json
import threading
import time
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class FailReason(StrEnum):
    """账号失效原因分类（见 app/deps.py 的 classify_failure）。"""

    AUTH_FAILED = "auth_failed"  # 认证失败（401/403）→ dead
    BANNED = "banned"  # 账号被封 → dead
    QUOTA_EXHAUSTED = "quota_exhausted"  # 额度耗尽 → cooling
    CF_CHALLENGE = "cf_challenge"  # 人机验证 / CF 拦截 → cooling


# 不可恢复的原因：标记 disabled 永久剔除；其余进入冷却
_DEAD_REASONS: frozenset[FailReason] = frozenset({FailReason.AUTH_FAILED, FailReason.BANNED})

# 默认冷却时长（秒）
COOLDOWN_SECONDS: float = 600.0

# 可恢复失效的冷却策略：action = "cooldown" / "disable"
_COOLDOWN_POLICY: dict[str, str] = {"action": "cooldown"}

# 按 FailReason 的冷却时长覆盖；未设置的原因回退到 COOLDOWN_SECONDS
_COOLDOWN_SECONDS_MAP: dict[FailReason, float] = {}


def set_cooldown_policy(
    action: str,
    seconds: float | None = None,
    seconds_map: dict[FailReason, float] | None = None,
) -> None:
    """设置非致命失效的处理策略与冷却时长。

    - ``"cooldown"``：冷却后恢复；可用 ``seconds`` 设全局默认值，或用 ``seconds_map`` 按原因覆盖。
    - ``"disable"``：直接标记 disabled，适合月额度或永不过期额度的上游。
    """
    if action not in ("cooldown", "disable"):
        raise ValueError(f"action must be 'cooldown' or 'disable', got {action!r}")
    _COOLDOWN_POLICY["action"] = action
    if seconds is not None:
        _COOLDOWN_SECONDS_MAP.setdefault(FailReason.QUOTA_EXHAUSTED, seconds)
        _COOLDOWN_SECONDS_MAP.setdefault(FailReason.CF_CHALLENGE, seconds)
    if seconds_map:
        _COOLDOWN_SECONDS_MAP.update(seconds_map)


class Account(BaseModel):
    """单个账号凭据。目标网站专属字段通过 extra=allow 容纳（见 upstream/account_fields.py）。"""

    model_config = ConfigDict(extra="allow")

    name: str
    source_email: str = ""
    created_at: str = ""
    disabled: bool = False
    fail_reason: FailReason | None = None
    cooldown_until: float = 0.0  # Unix 时间戳；0=无冷却

    @classmethod
    def from_file(cls, path: Path) -> Account:
        data = json.loads(path.read_text(encoding="utf-8"))
        if "name" not in data:
            # account/<name>.json 文件名即账号名，避免必填字段缺失导致启动崩溃
            data["name"] = path.stem
        return cls(**data)


class AccountPool:
    """账号池：round-robin 轮换可用子集（跳过 disabled 与未到期冷却），同步线程安全。"""

    def __init__(self, accounts: list[Account], account_dir: Path) -> None:
        # 按 name 排序保证 round-robin 游标确定性
        self._all: list[Account] = sorted(accounts, key=lambda a: a.name)
        self._dir = account_dir
        self._idx = 0
        self._lock = threading.Lock()
        self._on_changed: Callable[[], None] | None = None

    @classmethod
    def load(cls, account_dir: Path) -> AccountPool:
        """扫 account_dir 下的 *.json 构造账号池。目录不存在或无 json 抛 RuntimeError。"""
        if not account_dir.is_dir():
            raise RuntimeError(f"账号目录不存在: {account_dir}（请运行注册机注册账号）")
        files = sorted(account_dir.glob("*.json"))
        if not files:
            raise RuntimeError(f"账号目录无 *.json: {account_dir}（请运行注册机注册账号）")
        accounts = [Account.from_file(f) for f in files]
        return cls(accounts, account_dir)

    def set_on_changed(self, callback: Callable[[], None] | None) -> None:
        """设置账号池变化回调（用于自动补账号任务即时唤醒）。"""
        self._on_changed = callback

    def _notify_changed(self) -> None:
        """轻量通知回调；在锁内调用，不得做耗时/阻塞操作。"""
        if self._on_changed is not None:
            try:
                self._on_changed()
            except Exception:  # noqa: BLE001
                pass

    def all(self) -> list[Account]:
        """返回全部账号（含 disabled / 冷却中）。"""
        return list(self._all)

    def available_count(self) -> int:
        """当前可用账号数（未 disabled 且未在冷却期）。"""
        return len(self._available())

    def _is_available(self, a: Account) -> bool:
        if a.disabled:
            return False
        if a.cooldown_until and a.cooldown_until > time.time():
            return False
        return True

    def _available(self) -> list[Account]:
        return [a for a in self._all if self._is_available(a)]

    def next(self) -> Account:
        """round-robin 返回下一个可用账号；无可用抛 RuntimeError。"""
        with self._lock:
            avail = self._available()
            if not avail:
                raise RuntimeError("无可用账号（全部 disabled 或冷却中）")
            if self._idx >= len(avail):
                self._idx = 0
            acc = avail[self._idx]
            self._idx = (self._idx + 1) % len(avail)
            return acc

    def _save(self, acc: Account) -> None:
        """原子写 account/<name>.json（内部调用，需已持有锁）。"""
        self._dir.mkdir(parents=True, exist_ok=True)
        target = self._dir / f"{acc.name}.json"
        tmp = target.with_suffix(".json.tmp")
        payload = acc.model_dump(mode="json")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        tmp.replace(target)

    def mark_failed(self, acc: Account, reason: FailReason) -> None:
        """按原因标记账号：不可恢复→disabled（剔除），可恢复→按策略冷却或禁用。原子写回 json。"""
        with self._lock:
            acc.fail_reason = reason
            if reason in _DEAD_REASONS:
                acc.disabled = True
            elif _COOLDOWN_POLICY.get("action") == "disable":
                acc.disabled = True
            else:
                seconds = _COOLDOWN_SECONDS_MAP.get(reason, COOLDOWN_SECONDS)
                acc.cooldown_until = time.time() + seconds
            self._save(acc)
            self._notify_changed()

    def mark_disabled(self, acc: Account) -> None:
        """兼容旧名：等价于 mark_failed(AUTH_FAILED)。"""
        self.mark_failed(acc, FailReason.AUTH_FAILED)

    def add_or_update(self, acc: Account) -> None:
        """新增或替换账号，原子写盘并同步内存列表。"""
        with self._lock:
            self._save(acc)
            others = [a for a in self._all if a.name != acc.name]
            self._all = sorted([*others, acc], key=lambda a: a.name)
            avail_len = len(self._available())
            if avail_len and self._idx >= avail_len:
                self._idx = 0
            self._notify_changed()

    def remove(self, name: str) -> bool:
        """删除账号 json 并从内存池移除；存在返回 True。"""
        with self._lock:
            target = self._dir / f"{name}.json"
            existed = target.is_file()
            if existed:
                target.unlink()
            before = len(self._all)
            self._all = [a for a in self._all if a.name != name]
            avail_len = len(self._available())
            if avail_len and self._idx >= avail_len:
                self._idx = 0
            changed = existed or before != len(self._all)
            if changed:
                self._notify_changed()
            return changed

    def reload(self) -> None:
        """重新从磁盘加载全部账号，替换内存池。"""
        with self._lock:
            files = sorted(self._dir.glob("*.json"))
            self._all = [Account.from_file(f) for f in files]
            self._idx = 0
