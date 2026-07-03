# 认证分层 + 错误分类换号状态机

> 代码在 `app/deps.py`、`app/admin.py`、`app/account.py`。

## 一、认证分层

两套独立 key，互不影响：

| 层 | key | 配置 | 留空行为 |
|---|---|---|---|
| **/v1/** | `gateway.api_key` | `[gateway]` 段 `api_key` | **无认证**（任何人可调） |
| **/admin/** | `admin.auth_key` | `[admin]` 段 `auth_key` | **整个 admin 关闭**（端点返回 404 隐藏存在） |

### v1 key 真挂载（关键）

`app/deps.py:verify_api_key` 每个 `/v1` router 都要 `Depends(verify_api_key)`：
```python
@router.post("/v1/chat/completions")
async def chat_completions(req, client=Depends(get_client), _: None = Depends(verify_api_key)):
```
promptql2api 曾定义了 verify_api_key 但没挂到 router（形同虚设），本骨架**必须真挂载**，并有测试覆盖：
- 未设 key → 放行（无认证）；
- 设了 key 不带 → 401；错 key → 401；对 key → 200。

### admin key 留空 404

`app/admin.py:verify_admin_key` 在 `admin_auth_key` 为空时直接 `raise HTTPException(404)`，**隐藏端点存在**（而非返回 401 暴露端点）。校验方式：`Authorization: Bearer <key>` 或 `?auth_key=<key>` query 二选一。

## 二、错误分类换号状态机（`app/deps.py:classify_failure`）

把上游异常按 `FailReason` 分类，决定账号状态：

| FailReason | 触发条件 | 账号状态 | 恢复 |
|---|---|---|---|
| `AUTH_FAILED` | HTTP 401/403 或 body 含 `unauthorized`/`invalid token` 等 | **dead**（`disabled=True`） | 不可恢复，需人工换号 |
| `BANNED` | body 含 `banned`/`suspended`/`disabled`/`forbidden` 等 | dead | 不可恢复 |
| `QUOTA_EXHAUSTED` | HTTP 429 或 body 含 `quota`/`limit reached`/`credit` 等 | **cooling**（设 `cooldown_until`） | 冷却到期自动恢复 |
| `CF_CHALLENGE` | HTTP 451 或 body 含 `cloudflare`/`captcha`/`turnstile` 等 | cooling | 冷却到期恢复 |

`_DEAD_REASONS = {AUTH_FAILED, BANNED}`；其余进入冷却（默认 `COOLDOWN_SECONDS=600`）。

### 换号流程

`_RetryingClient.stream()` 包装上游 client：
1. 捕获上游异常 → `classify_failure(exc)`；
2. 若返回 FailReason → `pool.mark_failed(account, reason)` → 抛 **HTTP 503**；
3. 客户端重试同一请求 → `get_client` round-robin 取下一个可用账号（跳过 disabled 与未到期冷却）。

**为什么抛 503 而非自动重试同请求**：流式已 yield 部分内容后重试会重复输出。抛 503 让客户端重试换号即可。

### 与 orchestrator 重试正交

- `deps._RetryingClient`：账号级失效（认证/额度/封号）→ 503 换号。
- `orchestrator.stream_with_retry`：语义级拒绝（agent 不愿调工具）→ 换 tool 指令变体重试。
两者独立，分别处理不同类型的失败。

## 三、账号池轮询（`app/account.py`）

- **round-robin**：按 `name` 排序保证游标确定性，`_available()` 跳过 disabled 与未到期冷却。
- **并发安全**：`threading.Lock` 保护 `next/mark_failed/add/remove/reload`，锁内无 IO 不阻塞事件循环。
- **原子写**：`_save` 用 `tmp + replace` + `fcntl.flock` 原子写回 `account/<name>.json`。

## 四、按目标站定制

`classify_failure` 的 body 关键词列表是**上游耦合点**：不同站点的 banned/quota 关键词不同，需按抓包结果调整。详见 `references/capture-flow.md` 与 `references/upstream-adapters.md`。

## 五、测试要点

- 无 key → 放行；设 key 不带 → 401；错 key → 401；对 key → 200。
- admin 无 key → 404；错 key → 401；对 key → 200。
- `mark_failed(AUTH_FAILED)` → `disabled=True`；`mark_failed(QUOTA_EXHAUSTED)` → 冷却。
- 全部失效时 `next()` 抛 RuntimeError。
- 冷却到期后恢复可用。
