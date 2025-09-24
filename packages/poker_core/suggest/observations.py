from __future__ import annotations

import os
from collections.abc import Callable, Iterable

from poker_core.analysis import annotate_player_hand_from_gs
from poker_core.domain.actions import LegalAction
from poker_core.suggest.codes import SCodes
from poker_core.suggest.codes import mk_rationale as R
from poker_core.suggest.context import SuggestContext
from poker_core.suggest.hand_strength import derive_hand_strength
from poker_core.suggest.preflop_tables import combo_from_hole
from poker_core.suggest.types import Observation
from poker_core.suggest.utils import (
    calc_spr,
    classify_flop,
    derive_facing_size_tag,
    infer_last_aggressor_before,
    infer_pfr,
    infer_pot_type,
    nut_advantage,
    range_advantage,
    to_call_from_acts,
)
from poker_core.suggest.utils import (
    is_first_to_act as _is_first_to_act,
)
from poker_core.suggest.utils import is_ip as _is_ip
from poker_core.suggest.utils import (
    is_last_to_act as _is_last_to_act,
)
from poker_core.suggest.utils import (
    spr_bucket as _spr_bucket,
)

from .utils import infer_flop_hand_class_from_gs


def build_observation(
    gs,
    actor: int,
    acts: Iterable[LegalAction],
    *,
    annotate_fn: Callable | None = None,
    context: SuggestContext | None = None,
) -> tuple[Observation, list[dict]]:
    street = str(getattr(gs, "street", "preflop") or "preflop").lower()
    if street == "flop":
        return build_flop_observation(gs, actor, acts, annotate_fn=annotate_fn, context=context)
    if street == "turn":
        return build_turn_observation(gs, actor, acts, annotate_fn=annotate_fn, context=context)
    if street == "river":
        return build_river_observation(gs, actor, acts, annotate_fn=annotate_fn, context=context)
    return build_preflop_observation(gs, actor, acts, annotate_fn=annotate_fn, context=context)


def build_preflop_observation(
    gs,
    actor: int,
    acts: Iterable[LegalAction],
    *,
    annotate_fn: Callable | None = None,
    context: SuggestContext | None = None,
) -> tuple[Observation, list[dict]]:
    return _build_observation_common(
        gs, actor, acts, street_override="preflop", annotate_fn=annotate_fn, context=context
    )


def build_flop_observation(
    gs,
    actor: int,
    acts: Iterable[LegalAction],
    *,
    annotate_fn: Callable | None = None,
    context: SuggestContext | None = None,
) -> tuple[Observation, list[dict]]:
    return _build_observation_common(
        gs, actor, acts, street_override="flop", annotate_fn=annotate_fn, context=context
    )


def build_turn_observation(
    gs,
    actor: int,
    acts: Iterable[LegalAction],
    *,
    annotate_fn: Callable | None = None,
    context: SuggestContext | None = None,
) -> tuple[Observation, list[dict]]:
    return _build_observation_common(
        gs, actor, acts, street_override="turn", annotate_fn=annotate_fn, context=context
    )


def build_river_observation(
    gs,
    actor: int,
    acts: Iterable[LegalAction],
    *,
    annotate_fn: Callable | None = None,
    context: SuggestContext | None = None,
) -> tuple[Observation, list[dict]]:
    return _build_observation_common(
        gs, actor, acts, street_override="river", annotate_fn=annotate_fn, context=context
    )


def _build_observation_common(
    gs,
    actor: int,
    acts: Iterable[LegalAction],
    *,
    street_override: str,
    annotate_fn: Callable | None,
    context: SuggestContext | None,
) -> tuple[Observation, list[dict]]:
    acts_list = list(acts or [])
    pre_rationale: list[dict] = []

    annotate = annotate_fn or annotate_player_hand_from_gs

    try:
        ann = annotate(gs, actor)
        info = ann.get("info", {}) if isinstance(ann, dict) else {}
        tags = list(info.get("tags", []) or [])
        hand_class = str(info.get("hand_class", "unknown"))
    except Exception:
        tags = ["unknown"]
        hand_class = "unknown"
        pre_rationale.append(R(SCodes.WARN_ANALYSIS_MISSING))

    hand_id = str(getattr(gs, "hand_id", ""))
    bb = int(getattr(gs, "bb", 50))
    pot = int(getattr(gs, "pot", 0))
    to_call = int(to_call_from_acts(acts_list))

    table_mode = (os.getenv("SUGGEST_TABLE_MODE") or "HU").upper()
    button = int(getattr(gs, "button", 0))
    street = street_override or str(getattr(gs, "street", "preflop") or "preflop")

    ip = bool(_is_ip(actor, table_mode, button, street))
    first_to_act = bool(_is_first_to_act(actor, table_mode, button, street))
    last_to_act = bool(_is_last_to_act(actor, table_mode, button, street))

    players = list(getattr(gs, "players", []) or [])
    hero = players[actor] if actor < len(players) else None
    villain = players[1 - actor] if (1 - actor) < len(players) else None

    invested_total = 0
    eff_stack = 0
    try:
        for p in players[:2]:
            invested_total += int(getattr(p, "invested_street", 0) or 0)
    except Exception:
        invested_total = 0
    try:
        hero_stack = int(getattr(hero, "stack", 0) or 0)
        villain_stack = int(getattr(villain, "stack", 0) or 0)
        eff_stack = min(hero_stack, villain_stack)
    except Exception:
        eff_stack = 0

    pot_now = pot + invested_total

    # Adjust first_to_act based on action history in preflop
    # If pot significantly exceeds the initial blind investments, it's not the first action
    if street == "preflop" and table_mode == "HU":
        # Calculate expected pot for first action (SB + BB blinds)
        expected_first_action_pot = bb // 2 + bb  # SB 0.5bb + BB 1bb = 1.5bb
        # Only adjust if pot is much larger than expected (e.g., after a 3bet)
        if (
            pot_now > expected_first_action_pot + 4 * bb
        ):  # Need significant raise to not be first action
            first_to_act = False
    spr_val = calc_spr(pot_now, eff_stack)
    spr_bkt = _spr_bucket(spr_val)

    try:
        board = list(getattr(gs, "board", []) or [])
    except Exception:
        board = []
    texture_info = classify_flop(board) if board else {"texture": "na"}
    board_texture = str((texture_info or {}).get("texture", "na"))

    # 先推断 pot_type 以便在翻后缺事件时做安全回退
    try:
        pot_type = str(infer_pot_type(gs))
    except Exception:
        pot_type = "single_raised"

    role = "na"
    try:
        pfr = infer_pfr(gs)
        if pfr is not None:
            role = "pfr" if int(pfr) == int(actor) else "caller"
        else:
            # 回退：不再用按钮来猜测 PFR；保留未知
            role = "na"
    except Exception:
        role = "na"

    try:
        combo = combo_from_hole(getattr(hero, "hole", []) if hero is not None else [])
    except Exception:
        combo = None

    # Flop-specific hand class override & advantages
    if street == "flop":
        try:
            hand_class = infer_flop_hand_class_from_gs(gs, actor)
        except Exception:
            pass
        range_adv = bool(range_advantage(board_texture, role))
        nut_adv = bool(nut_advantage(board_texture, role))
    else:
        range_adv = False
        nut_adv = False

    facing_size_tag = derive_facing_size_tag(to_call, pot_now)

    # pot_type 已在上文计算

    # teaching field: last aggressor before current street
    try:
        last_aggr = infer_last_aggressor_before(gs, street)
    except Exception:
        last_aggr = None

    hand_strength = derive_hand_strength(street, tags, hand_class)

    try:
        last_bet = int(getattr(gs, "last_bet", 0) or 0)
    except Exception:
        last_bet = 0

    obs = Observation(
        hand_id=hand_id,
        actor=int(actor),
        street=street,
        bb=bb,
        pot=pot,
        to_call=to_call,
        acts=acts_list,
        tags=tags,
        hand_class=str(hand_class),
        table_mode=table_mode,
        spr_bucket=str(spr_bkt or "na"),
        board_texture=board_texture,
        ip=ip,
        first_to_act=first_to_act,
        last_to_act=last_to_act,
        pot_now=int(pot_now),
        combo=str(combo or ""),
        last_bet=last_bet,
        button=int(button),
        hand_strength=hand_strength,
        role=role,
        range_adv=range_adv,
        nut_adv=nut_adv,
        facing_size_tag=facing_size_tag,
        pot_type=pot_type,
        last_aggressor=last_aggr,
        context=context,
    )

    return obs, pre_rationale


__all__ = [
    "build_observation",
    "build_preflop_observation",
    "build_flop_observation",
    "build_turn_observation",
    "build_river_observation",
]
