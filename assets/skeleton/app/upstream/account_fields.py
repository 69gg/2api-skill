"""上游账号专属凭据字段说明（文档性质）。

:class:`~app.account.Account` 用 ``extra=allow`` 容纳这些字段。换上游时在此列出该上游需要的
凭据字段，供注册机写入与 admin 展示参考。示例（PromptQL）：hasura_lux / project_id / project_name。
"""
from __future__ import annotations

# 目标网站账号凭据字段（占位，按目标站填写）。注册机注册成功后写 account/<name>.json，
# 含这些字段 + name/created_at/disabled 等通用字段。
UPSTREAM_ACCOUNT_FIELDS: dict[str, str] = {
    # "<field_name>": "<字段说明>",
}
