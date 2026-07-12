# token 用量

> 诚实原则：上游无真实 usage 时返回估算值并标注，绝不编造精确值。代码在 `app/tokens.py`。

## 一、优先级

1. **上游真实 usage**：`IREvent.usage_delta`（parser 从上游 usage 字段填入），含 `input_tokens/output_tokens/thinking_tokens/cached_tokens/cache_creation_tokens/model/provider`。
2. **CJK 感知估算**（`estimate_tokens_cjk`）：`cjk*1.3 + ascii/3.5 + other*1.0`，对中英混排比纯 tiktoken cl100k 友好（参考 gpt2api）。
3. **tiktoken 兜底**：`estimate_tokens` 用 tiktoken cl100k_base 近似（claude 系无对应 encoding，统一 cl100k 近似）；tiktoken 不可用时回退 CJK 估算。

## 二、first_usage vs sum_usage

- **first_usage**：取首个非零 usage。agent 一次问答可能跑多轮（每轮重读全上下文，input_tokens 含大量缓存命中），累加会重复算系统提示。取首轮（final_response 那轮）最接近用户感知单次用量。
- **sum_usage**：累加所有 usage（含首个 model/provider），用于需要总量场景。

## 三、三家 usage 字段映射

| 协议 | 字段 |
|---|---|
| OpenAI Chat | `{"prompt_tokens", "completion_tokens", "total_tokens"}`；有思维链时 + `completion_tokens_details.reasoning_tokens` |
| Anthropic Messages | `{"input_tokens", "output_tokens"}`；有思维链时可选 + `thinking_tokens` |
| OpenAI Responses | `{"input_tokens", "output_tokens"}`；有思维链时 + `output_tokens_details.reasoning_tokens` |

无真实 usage 时填 `estimate_tokens(prompt)` / `estimate_tokens(completion)`。`reasoning_tokens` 是 completion/output 的**子集明细**，不重复计入 total。

## 四、流式累计

流式下收集所有 `usage_delta`，末尾用 `first_usage`（见 `app/adapters/openai_chat.py:_gen_stream`）——不是逐块累加，因伪流式整块返回；真流式若有逐块 usage 也应 `first_usage` 取首个非零。

## 五、测试要点

- 纯中文估算：`max(1, int(cjk*1.3))`；纯 ASCII：`max(1, int(ascii/3.5))`；空串为 0。
- first_usage 取首个非零，全零返回空 Usage。
- sum_usage 累加并保留首个 model/provider。
