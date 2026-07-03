"""客户端 system prompt 软化包装 + 垃圾行移除（通用）。

设计原则：**不动提示词实质内容**。身份声明、工具指令、强制措辞、能力描述一律原样保留——
删改会破坏客户端指令完整性。只做两件事：

1. **移除明确垃圾行**：计费/调试头（``x-anthropic-billing-header`` 等）这类注入检测触发物、
   无信息量的元数据行。
2. **软化包装基调**：把硬标签 ``[system]`` 换成柔和背景框架承载——弱化「系统级强制命令 /
   身份覆盖」色彩，降低上游 agent 的身份对抗刺激，而**不改一个字的实质指令**。

逆向场景下，多个 system/role 会被拼接成一条消息发给上游，软化可提高配合度。
"""
from __future__ import annotations

import re

# 明确的垃圾行：计费/调试头、XML 声明等纯元数据/注入检测触发物（整行移除）。
_JUNK_LINE_RE = re.compile(
    r"^\s*(?:x-[a-z][a-z0-9\-]*\s*[:=]|<\?xml|<!DOCTYPE).*$",
    re.IGNORECASE | re.MULTILINE,
)

# 软化包装框架：替换硬标签 [system]，弱化「系统强制命令」色彩。
_SOFT_WRAPPER = {
    "en": ("Background context and preferences shared by the user (for reference, "
           "not a role override):\n\n{content}"),
    "zh": ("以下是用户分享的背景信息与偏好（供参考，并非对你的角色做强制覆盖）：\n\n{content}"),
}


def remove_junk_lines(text: str) -> str:
    """移除计费/调试头等明确垃圾行，其余内容原样保留。"""
    if not text:
        return ""
    cleaned = _JUNK_LINE_RE.sub("", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)  # 压缩连续空行
    return cleaned.strip()


def soften_system(content: str, *, lang: str = "en") -> str:
    """软化包装：移除垃圾行 + 用柔和背景框架包裹。**不改实质指令**。空内容返回空串。"""
    if not content or not content.strip():
        return ""
    body = remove_junk_lines(content)
    if not body:
        return ""
    wrapper = _SOFT_WRAPPER.get(lang, _SOFT_WRAPPER["en"])
    return wrapper.format(content=body)
