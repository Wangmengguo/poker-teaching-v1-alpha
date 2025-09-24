"""Shared sizing/probability helpers for suggest policies/services."""

from __future__ import annotations

from typing import Final

from .utils import size_to_amount

_SIZING_TAGS: Final[set[str]] = {"third", "half", "two_third", "pot", "all_in"}


def pot_odds(to_call: int, pot_now: int) -> float:
    """Compute pot odds using the invariant pot_now + to_call as denominator.

    pot_now 应当包含对手已投入与盲注，但排除英雄尚未跟注的金额。
    """

    tc = max(0, int(to_call or 0))
    pn = max(0, int(pot_now or 0))
    denom = pn + tc
    if denom <= 0:
        # to_call>0 且锅内无筹码时，给出最大赔率 1.0；否则视为 0。
        return 1.0 if tc > 0 else 0.0
    return float(tc) / float(denom)


def mdf(to_call: int, pot_now: int) -> float:
    """Minimum defence frequency = 1 - pot_odds."""

    return max(0.0, min(1.0, 1.0 - pot_odds(to_call, pot_now)))


def size_from_bb(bb_mult: float, bb: int) -> int:
    """Translate blind-multiple sizing into absolute chips (rounded to int)."""

    if bb <= 0:
        raise ValueError("bb must be positive")
    return max(1, int(round(float(bb_mult) * float(bb))))


def size_from_tag(size_tag: str, pot_now: int, last_bet: int, bb: int) -> int:
    """Convert canonical size_tag into absolute bet amount (bet semantics)."""

    if size_tag not in _SIZING_TAGS:
        raise ValueError(f"Unsupported size_tag: {size_tag}")
    amt = size_to_amount(int(pot_now), int(last_bet), size_tag, int(bb))
    if amt is None:
        raise ValueError(f"Unable to derive amount from size_tag: {size_tag}")
    return max(int(bb), int(amt))


__all__ = ["pot_odds", "mdf", "size_from_bb", "size_from_tag"]
