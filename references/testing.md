# 测试规范

> 代码在 `tests/` 与 `scripts/`。骨架已含完整测试套件。

## 一、单元测试策略

- **不依赖网络**：用 `FakeProvider`（`tests/conftest.py`）喂固定 IREvent 序列，验证 adapter 输出格式。
- **FastAPI dependency_overrides**：`app.dependency_overrides[get_client] = lambda: FakeProvider(...)` 替换上游 client，每个测试后清理。
- **lru_cache 清理**：`clear_settings_cache()` 在 autouse fixture 中清理，避免 config 缓存串扰。
- **真实样本**：`conftest.py` 放真实抓取的事件样本（如有），供 events/parser 测试复用。

## 二、测试组织

| 文件 | 覆盖 |
|---|---|
| `tests/test_config.py` | toml 加载、段平铺、别名、文件缺失回退默认、lru_cache |
| `tests/test_account.py` | round-robin、错误分类换号、冷却、增删改、全失效抛错、extra 字段 |
| `tests/test_tokens.py` | CJK 估算、first_usage、sum_usage |
| `tests/test_tools.py` | 三级解析、tolerant_parse、strip、directive、拒绝跳过、真流式状态机 |
| `tests/test_streaming.py` | warmup/guard 双缓冲、拦截前缀、safe_sse_stream |
| `tests/test_adapters.py` | 三家 API（chat/responses/messages）流式+非流式+tool call、**reasoning/thinking 透传**（含与 tool 并存）、v1 key 校验、count_tokens、models |
| `tests/test_admin.py` | 留空关闭(404)、错 key(401)、CRUD + reload、敏感字段隐藏 |

## 三、测试要点

- **真流式状态机**：覆盖跨 chunk 切分（`<tool_ca`|`ll>{...}`、`{"name":"x","ar`|`guments":1}}`）、围栏内 `}` 字面量、未闭合围栏。
- **v1 key 真挂载**：未设 key 放行；设 key 不带 → 401；错 key → 401；对 key → 200。
- **错误分类换号**：AUTH_FAILED/BANNED → disabled；QUOTA_EXHAUSTED/CF_CHALLENGE → 冷却到期恢复。

## 四、端到端冒烟（`scripts/e2e_smoke.py`）

对运行中的 2api 网关跑端到端冒烟（跨生成项目通用，仅用标准库）：

```bash
uv run uvicorn app.main:app --port 8088 &
python scripts/e2e_smoke.py --base-url http://localhost:8088 --model <id> --suite models,chat,stream,tool
```

测：`GET /v1/models`、`POST /v1/chat/completions`（非流+流）、带 tools 的 tool_call 解析。每步 PASS/FAIL，非 200 时打印 body。

## 五、e2e 脚本（可选）

`skeleton/scripts/e2e_*.py` 用 OpenAI/Anthropic SDK 打本地网关，跑更复杂的场景（多轮对话、多模态、tool call 命中率统计）。需先起网关再跑。

## 六、lint 与单测门槛

```bash
uv run pytest        # 必须全绿
uv run ruff check .  # 必须通过
```

骨架已实现并通过这些测试（见 `tests/`）。
