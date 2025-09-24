"""
PokerKit 适配器

使用 PokerKit 库评估 7 张牌的强度。
"""

import functools
from collections.abc import Sequence

from .interfaces import EvalResult, EvaluationError, HandEvaluator, Strength


def _canon_card(c: str) -> str:
    c = c.strip()
    if len(c) == 3 and c[:2] == "10":
        return "T" + c[-1].lower()  # 花色保持小写，PokerKit期望小写
    r, s = c[0].upper(), c[1].lower()  # 牌面大写，花色小写
    return r + s


def _canon7(hole: Sequence[str], board: Sequence[str]) -> tuple[str, ...]:
    if len(hole) != 2 or len(board) != 5:
        raise ValueError("evaluate7 expects exactly 2 hole cards and 5 board cards")
    cards = tuple(sorted(_canon_card(x) for x in list(hole) + list(board)))
    if len(set(cards)) != 7:
        # 重复牌报我们自己的错误类型，便于上层捕获并回退
        raise EvaluationError("duplicate_card", detail={"cards": cards})
    return cards  # 作为缓存键 & 规范化表示


class PokerKitEvaluator(HandEvaluator):
    def __init__(self):
        # 延迟导入，隔离依赖
        from pokerkit import StandardHighHand

        self._StandardHighHand = StandardHighHand

    @functools.lru_cache(maxsize=4096)
    def _eval_cached(self, canon: tuple[str, ...]) -> EvalResult:
        """
        canon: 7 张牌的规范化元组（已排序、去重校验过）
        注意：from_game 需要 2+5；对高牌评估来说分界不影响结果。
        """
        try:
            hole = "".join(canon[:2])
            board = "".join(canon[2:])
            hand = self._StandardHighHand.from_game(hole, board)
            # 直接使用Card对象的rank和suit属性，最高效的方式
            best5 = [f"{c.rank}{c.suit}" for c in hand.cards]
            return EvalResult(best5=best5, strength=Strength(hand))
        except Exception as e:
            # 统一包装，方便上层降级到 FallbackEvaluator
            raise EvaluationError("pokerkit_error", original=str(e))

    def evaluate7(self, hole: Sequence[str], board: Sequence[str]) -> EvalResult:
        canon = _canon7(hole, board)
        return self._eval_cached(canon)
