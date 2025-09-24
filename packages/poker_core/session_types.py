# packages/poker_core/session_types.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SessionView:
    session_id: str
    button: int  # 0 or 1
    stacks: tuple[int, int]  # (p0, p1)
    hand_no: int  # 第几手（从 1 开始）
    current_hand_id: str | None = None


@dataclass(frozen=True)
class NextHandPlan:
    session_id: str
    next_button: int
    stacks: tuple[int, int]
    next_hand_no: int
    seed: int | None = None
