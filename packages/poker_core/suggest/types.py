# poker_core/suggest/types.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from poker_core.domain.actions import LegalAction
from poker_core.suggest.context import SuggestContext

from .hand_strength import HandStrength


@dataclass(frozen=True)
class Observation:
    hand_id: str
    actor: int
    street: str  # preflop / flop / turn / river
    bb: int
    pot: int
    to_call: int
    acts: list[LegalAction]
    tags: list[str]
    hand_class: str
    # v1 additions (PR-0 baseline; defaults keep compatibility)
    table_mode: str = "HU"  # HU/4max/6max
    button: int = 0  # seat index of button (SB in HU)
    spr_bucket: str = "na"  # low/mid/high/na
    board_texture: str = "na"  # dry/semi/wet/na (non-flop: na)
    ip: bool = False
    # 行动顺序标注（教学辅助；策略不依赖）
    first_to_act: bool = False
    last_to_act: bool = False
    # PR-1: preflop pot-odds 需要的“当前池”口径（含盲注/已投入）
    pot_now: int = 0
    # PR-1: 169 栅格组合标签（如 'AKs','KQo','TT'；未知为空串）
    combo: str = ""
    last_bet: int = 0
    hand_strength: HandStrength | None = None
    # PR-2 (Flop v1): role/MDF helpers and facing size tag
    role: str = "na"  # pfr | caller | na
    range_adv: bool = False  # heuristic range advantage on flop
    nut_adv: bool = False  # heuristic nut advantage on flop
    facing_size_tag: str = "na"  # third | half | two_third+ | na
    # v1.1: pot type classification (single_raised|limped|threebet)
    pot_type: str = "single_raised"
    # teaching field: 上一轮最后一次加注者（进入本街之前），None 表示未知
    last_aggressor: int | None = None
    context: SuggestContext | None = None


@dataclass(frozen=True)
class PolicyConfig:
    open_size_bb: float = 2.5
    call_threshold_bb: int = 3
    pot_odds_threshold: float = 0.33
    pot_odds_threshold_callrange: float = 0.40


# For postflop sizing annotations (preflop keeps meta.open_bb instead)
SizeTag = Literal["third", "half", "two_third", "pot", "all_in"]

__all__ = [
    "Observation",
    "PolicyConfig",
    "SizeTag",
]
