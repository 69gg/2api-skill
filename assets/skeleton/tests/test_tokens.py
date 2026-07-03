"""token 用量测试：CJK 估算、first_usage、sum_usage。"""
from __future__ import annotations

from app.events import Usage
from app.tokens import estimate_tokens_cjk, first_usage, sum_usage


def test_cjk_estimate():
    # 纯中文：1.3/字
    assert estimate_tokens_cjk("你好") == max(1, int(2 * 1.3))
    # 纯 ASCII：/3.5
    assert estimate_tokens_cjk("hello") == max(1, int(5 / 3.5))
    # 空串
    assert estimate_tokens_cjk("") == 0


def test_first_usage_picks_first_nonzero():
    u = first_usage([Usage(), Usage(input_tokens=5, output_tokens=3), Usage(input_tokens=10)])
    assert u.input_tokens == 5
    assert u.output_tokens == 3


def test_first_usage_all_zero():
    assert first_usage([Usage(), Usage()]) == Usage()


def test_sum_usage():
    total = sum_usage([Usage(input_tokens=1, output_tokens=2, model="m"), Usage(input_tokens=3, output_tokens=4)])
    assert total.input_tokens == 4
    assert total.output_tokens == 6
    assert total.model == "m"
