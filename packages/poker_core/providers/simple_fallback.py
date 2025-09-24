"""
提供一个简单的启发式评估器，用于在 PokerKit 不可用时 fallback。
"""

from collections.abc import Sequence

from poker_core.cards import get_rank_value, parse_card

from .interfaces import EvalResult, HandEvaluator, Strength


def _score7(hole: Sequence[str], board: Sequence[str]) -> tuple[int, list[str]]:
    # 教学启发式：取7张里按 rank 值最高的5张求和，返回(分数, 最佳五张)
    cards = list(hole) + list(board)
    # 按 rank 值降序
    cards_sorted = sorted(cards, key=lambda c: get_rank_value(parse_card(c)[0]), reverse=True)
    best5 = cards_sorted[:5]
    score = sum(get_rank_value(parse_card(c)[0]) for c in best5)
    return score, best5


class SimpleFallbackEvaluator(HandEvaluator):
    def evaluate7(self, hole, board):
        score, best5 = _score7(hole, board)
        return EvalResult(best5=best5, strength=Strength(score), category=None)
