"""
选择合适的评估器。

- 优先使用 PokerKit 评估器
- 若 PokerKit 不可用，则使用简单的启发式评估器
- 支持环境变量控制：POKER_EVAL=pokerkit 或 POKER_EVAL=fallback
"""

import os
from functools import lru_cache

from .interfaces import HandEvaluator
from .simple_fallback import SimpleFallbackEvaluator


def _new_pokerkit() -> HandEvaluator:
    from .pokerkit_adapter import PokerKitEvaluator

    return PokerKitEvaluator()


@lru_cache(maxsize=1)
def get_evaluator() -> HandEvaluator:
    want = (os.getenv("POKER_EVAL") or "").strip().lower()
    if want == "pokerkit":
        # 强制使用 pokerkit；若没装就抛错（显式暴露问题）
        return _new_pokerkit()
    if want == "fallback":
        return SimpleFallbackEvaluator()

    # 未设置：优先 pokerkit，失败则回退
    try:
        return _new_pokerkit()
    except Exception:
        # 可加一次性日志：当前使用 fallback
        return SimpleFallbackEvaluator()
