"""agent 拒绝 / 身份识破检测（通用中英文措辞）。

webchat 的 agent 在拒绝「伪造工具调用」时常出现固定措辞：直接拒绝（"I can't"）、
声明越权（"not how I operate"）、亮明自身身份。检测到即判定拒绝，:mod:`app.orchestrator`
据此重试（换 tool 指令变体）。**换上游时若该上游有特有的拒绝措辞，在此补充。**
"""
from __future__ import annotations

# agent 拒绝 / 声明越权时常出现的措辞（中英）。命中任一即视为拒绝信号。
REFUSAL_PHRASES: tuple[str, ...] = (
    # 直接拒绝
    "i can't", "i cannot", "i won't", "i will not",
    "i'm not going to", "i am not going to",
    "i'm not able", "i am not able",
    "can't help", "cannot help", "can't generate", "can't produce", "can't emit",
    # 操作方式声明（"that's not how I operate"）
    "not how i operate", "isn't how i operate", "i don't operate",
    # 声明越权 / 不在能力范围
    "isn't one of my capabilities", "outside my capabilities", "beyond what i do",
    "not within my capabilities", "i won't fabricate", "i'm not able to fabricate",
    # 中文
    "我不能", "我无法", "我不会", "我做不到",
    "不是我的能力", "超出我的能力", "不在我的能力范围",
)


def looks_refusal(text: str) -> bool:
    """文本是否命中拒绝 / 识破措辞（子串匹配，大小写不敏感）。"""
    if not text:
        return False
    low = text.lower()
    return any(p in low for p in REFUSAL_PHRASES)


def is_refusal(text: str, *, has_tools: bool) -> bool:
    """判定一次 agent 回复是否构成「拒绝 / 识破」需要重试。

    - 无 tools 的纯对话请求不判拒绝（agent 拒绝可能是合理的，如越界内容）。
    - 有 tools 的请求命中拒绝措辞 → True（需重试换 tool 指令变体）。
    """
    if not has_tools or not text:
        return False
    return looks_refusal(text)
