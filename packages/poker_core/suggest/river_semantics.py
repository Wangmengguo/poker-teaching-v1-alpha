from __future__ import annotations

import os
from collections import Counter
from functools import lru_cache
from itertools import combinations
from pathlib import Path
from typing import Any

import yaml  # type: ignore
from poker_core.cards import RANK_ORDER
from poker_core.cards import parse_card

from .types import Observation

_CATEGORIES = {
    "high_card": 0,
    "one_pair": 1,
    "two_pair": 2,
    "three_kind": 3,
    "straight": 4,
    "flush": 5,
    "full_house": 6,
    "four_kind": 7,
    "straight_flush": 8,
}


def _river_rules_path() -> Path:
    override = os.getenv("SUGGEST_RIVER_RULES_FILE")
    if override:
        p = Path(override).expanduser().resolve()
        if p.exists():
            return p
    return Path(__file__).resolve().parents[3] / "rules" / "river.yaml"


@lru_cache(maxsize=1)
def _load_river_rules() -> dict[str, Any]:
    path = _river_rules_path()
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def analyze_river_context(obs: Observation) -> dict[str, Any]:
    hole = list(obs.hole or [])
    board = list(obs.board or [])
    if len(hole) < 2 or len(board) < 5:
        return {
            "tier": "unknown",
            "blockers": [],
            "combo": None,
        }

    best = _best_hand_info(hole, board)
    tier = _tier_from_best(best, board, hole)
    blockers = _detect_blockers(hole, board)

    return {
        "tier": tier,
        "blockers": blockers,
        "combo": best,
    }


def apply_river_no_bet_adjustment(
    action: str | None, size_tag: str | None, ctx: dict[str, Any]
) -> tuple[str | None, str | None, str | None]:
    if not ctx:
        return action, size_tag, None
    cfg = _load_river_rules()
    tiers = cfg.get("tiers") if isinstance(cfg, dict) else {}
    tier_cfg = tiers.get(ctx.get("tier")) if isinstance(tiers, dict) else {}
    if not isinstance(tier_cfg, dict):
        return action, size_tag, None

    blockers_cfg = tier_cfg.get("blockers") if isinstance(tier_cfg, dict) else {}
    default_cfg = tier_cfg.get("default") if isinstance(tier_cfg, dict) else {}
    plan: str | None = None

    blockers = list(ctx.get("blockers") or [])
    priority = cfg.get("blocker_priority") if isinstance(cfg, dict) else None
    if isinstance(priority, list) and priority:
        ordered = [blk for blk in priority if blk in blockers]
        ordered.extend([blk for blk in blockers if blk not in ordered])
        blockers = ordered

    for blk in blockers:
        blk_cfg = blockers_cfg.get(blk) if isinstance(blockers_cfg, dict) else None
        if isinstance(blk_cfg, dict) and blk_cfg:
            action = blk_cfg.get("action", action)
            size_tag = blk_cfg.get("size_tag", size_tag)
            plan = blk_cfg.get("plan", plan)
            return action, size_tag, plan

    if isinstance(default_cfg, dict) and default_cfg:
        action = default_cfg.get("action", action)
        size_tag = default_cfg.get("size_tag", size_tag)
        plan = default_cfg.get("plan", plan)
    return action, size_tag, plan


def apply_river_facing_adjustment(
    ctx: dict[str, Any], facing_size_tag: str
) -> dict[str, Any] | None:
    if not ctx:
        return None
    cfg = _load_river_rules()
    tiers = cfg.get("tiers") if isinstance(cfg, dict) else {}
    tier_cfg = tiers.get(ctx.get("tier")) if isinstance(tiers, dict) else {}
    if not isinstance(tier_cfg, dict):
        return None
    facing_cfg = tier_cfg.get("facing") if isinstance(tier_cfg, dict) else {}
    if not isinstance(facing_cfg, dict) or not facing_cfg:
        return None

    size_map = cfg.get("facing_size_map") if isinstance(cfg, dict) else {}
    key = None
    if isinstance(size_map, dict):
        for label, tags in size_map.items():
            if isinstance(tags, (list, tuple, set)) and facing_size_tag in tags:
                key = label
                break
    if key is None:
        key = facing_size_tag if facing_size_tag and facing_size_tag != "na" else None

    if key and key in facing_cfg:
        entry = facing_cfg.get(key)
        if isinstance(entry, dict) and entry:
            return entry
    default_entry = facing_cfg.get("default")
    if isinstance(default_entry, dict) and default_entry:
        return default_entry
    return None


def _best_hand_info(hole: list[str], board: list[str]) -> dict[str, Any]:
    cards = hole + board
    hero_set = set(hole)
    best_info: dict[str, Any] | None = None

    for combo in combinations(cards, 5):
        info = _classify_combo(combo)
        info["hero_use"] = len(hero_set & set(combo))
        info["combo"] = combo
        if best_info is None:
            best_info = info
            continue
        if _compare_combo(info, best_info) > 0:
            best_info = info

    return best_info or {"category": "high_card", "rank": 0, "hero_use": 0, "combo": tuple()}


def _compare_combo(cur: dict[str, Any], other: dict[str, Any]) -> int:
    r1 = _CATEGORIES.get(cur.get("category", "high_card"), 0)
    r2 = _CATEGORIES.get(other.get("category", "high_card"), 0)
    if r1 != r2:
        return 1 if r1 > r2 else -1
    primary1 = tuple(cur.get("primary_ranks") or [])
    primary2 = tuple(other.get("primary_ranks") or [])
    if primary1 != primary2:
        return 1 if primary1 > primary2 else -1
    kick1 = tuple(cur.get("kickers") or [])
    kick2 = tuple(other.get("kickers") or [])
    if kick1 != kick2:
        return 1 if kick1 > kick2 else -1
    return 0


def _classify_combo(cards: tuple[str, ...]) -> dict[str, Any]:
    ranks = []
    suits = []
    values = []
    for card in cards:
        rank, suit = parse_card(card)
        ranks.append(rank)
        suits.append(suit)
        values.append(RANK_ORDER.get(rank, 0))

    value_counts = Counter(values)
    counts_sorted = sorted(value_counts.items(), key=lambda x: (-x[1], -x[0]))
    is_flush = len(set(suits)) == 1
    straight, straight_high = _is_straight(values)

    if is_flush and straight:
        return {
            "category": "straight_flush",
            "rank": _CATEGORIES["straight_flush"],
            "primary_ranks": [straight_high],
            "kickers": [],
        }
    if counts_sorted[0][1] == 4:
        four_rank = counts_sorted[0][0]
        kicker = max(v for v, c in value_counts.items() if c == 1)
        return {
            "category": "four_kind",
            "rank": _CATEGORIES["four_kind"],
            "primary_ranks": [four_rank],
            "kickers": [kicker],
        }
    if counts_sorted[0][1] == 3 and counts_sorted[1][1] == 2:
        triple = counts_sorted[0][0]
        pair = counts_sorted[1][0]
        return {
            "category": "full_house",
            "rank": _CATEGORIES["full_house"],
            "primary_ranks": [triple, pair],
            "kickers": [],
        }
    if is_flush:
        ordered = sorted(values, reverse=True)
        return {
            "category": "flush",
            "rank": _CATEGORIES["flush"],
            "primary_ranks": ordered,
            "kickers": [],
        }
    if straight:
        return {
            "category": "straight",
            "rank": _CATEGORIES["straight"],
            "primary_ranks": [straight_high],
            "kickers": [],
        }
    if counts_sorted[0][1] == 3:
        triple = counts_sorted[0][0]
        kickers = sorted((v for v, c in value_counts.items() if c == 1), reverse=True)
        return {
            "category": "three_kind",
            "rank": _CATEGORIES["three_kind"],
            "primary_ranks": [triple],
            "kickers": kickers,
        }
    pairs = [v for v, c in value_counts.items() if c == 2]
    if len(pairs) >= 2:
        top_two = sorted(pairs, reverse=True)[:2]
        kicker = max(v for v, c in value_counts.items() if c == 1)
        return {
            "category": "two_pair",
            "rank": _CATEGORIES["two_pair"],
            "primary_ranks": top_two,
            "kickers": [kicker],
        }
    if len(pairs) == 1:
        pair_rank = pairs[0]
        kickers = sorted((v for v, c in value_counts.items() if c == 1), reverse=True)
        return {
            "category": "one_pair",
            "rank": _CATEGORIES["one_pair"],
            "primary_ranks": [pair_rank],
            "kickers": kickers,
        }
    ordered = sorted(values, reverse=True)
    return {
        "category": "high_card",
        "rank": _CATEGORIES["high_card"],
        "primary_ranks": ordered,
        "kickers": ordered,
    }


def _is_straight(values: list[int]) -> tuple[bool, int]:
    uniq = sorted(set(values))
    if len(uniq) >= 5:
        for i in range(len(uniq) - 4):
            window = uniq[i : i + 5]
            if window[-1] - window[0] == 4:
                return True, window[-1]
    # Wheel check A-2-3-4-5
    if {14, 5, 4, 3, 2}.issubset(uniq):
        return True, 5
    return False, 0


def _tier_from_best(best: dict[str, Any], board: list[str], hole: list[str]) -> str:
    category = best.get("category", "high_card")
    hero_use = int(best.get("hero_use") or 0)
    if category in {
        "straight_flush",
        "four_kind",
        "full_house",
        "flush",
        "straight",
        "three_kind",
        "two_pair",
    }:
        if hero_use == 0:
            if _board_combo_is_nuts(best):
                return "strong_value"
            return "weak_showdown"
        return "strong_value"

    board_values = sorted({RANK_ORDER.get(parse_card(card)[0], 0) for card in board}, reverse=True)
    board_top = board_values[0] if board_values else 0
    board_second = board_values[1] if len(board_values) > 1 else board_top
    hero_vals = [RANK_ORDER.get(parse_card(card)[0], 0) for card in hole]

    if category == "one_pair":
        pair_rank = (best.get("primary_ranks") or [0])[0]
        pocket_pair = len(set(hero_vals)) == 1 and len(hero_vals) == 2
        if pocket_pair and hero_vals[0] > board_top:
            return "strong_value"
        if hero_use >= 1 and pair_rank >= board_top:
            return "strong_value"
        if hero_use >= 1 and pair_rank >= board_second:
            return "medium_value"
        return "weak_showdown"

    if category == "high_card":
        highest = max(hero_vals) if hero_vals else 0
        if highest >= RANK_ORDER.get("A", 14):
            return "weak_showdown"
        return "air"

    return "air"


def _board_combo_is_nuts(best: dict[str, Any]) -> bool:
    """Return True if the board alone makes an unbeatable hand."""

    category = best.get("category")
    if category == "straight_flush":
        high = (best.get("primary_ranks") or [0])[0]
        return high == 14
    if category == "four_kind":
        kicker = (best.get("kickers") or [0])[0]
        return kicker == 14
    return False


def _detect_blockers(hole: list[str], board: list[str]) -> list[str]:
    blockers: list[str] = []
    hole_cards = [parse_card(card) for card in hole]
    board_cards = [parse_card(card) for card in board]

    # Nut flush blocker: hold the highest suit card matching board suit when flush is possible.
    suit_counts = Counter(suit for _, suit in board_cards)
    if suit_counts:
        suit, count = max(suit_counts.items(), key=lambda x: x[1])
        if count >= 3:
            if any(rank == "A" and s == suit for rank, s in hole_cards):
                blockers.append("nut_flush_blocker")

    # Straight blockers: board has four to a straight and hero holds endpoint.
    board_vals = {RANK_ORDER.get(rank, 0) for rank, _ in board_cards}
    hero_vals = {RANK_ORDER.get(rank, 0) for rank, _ in hole_cards}
    for start in range(2, 11):
        seq = {start, start + 1, start + 2, start + 3}
        if len(seq & board_vals) >= 4:
            needed = {start - 1, start + 4}
            normalized = set()
            for val in needed:
                if val == 1:
                    normalized.add(14)
                elif 2 <= val <= 14:
                    normalized.add(val)
            if hero_vals & normalized:
                blockers.append("straight_blocker")
                break
    else:
        # Wheel-specific: 2-3-4-5 needs Ace or Six
        if {2, 3, 4, 5}.issubset(board_vals):
            if hero_vals & {6, 14}:
                blockers.append("straight_blocker")

    # Full house blockers when board is heavily paired
    board_rank_counts = Counter(rank for rank, _ in board_cards)
    if any(cnt >= 3 for cnt in board_rank_counts.values()):
        kicker_ranks = {rank for rank, cnt in board_rank_counts.items() if cnt == 1}
        if any(rank in kicker_ranks for rank, _ in hole_cards):
            blockers.append("full_house_blocker")
    elif sum(1 for cnt in board_rank_counts.values() if cnt == 2) >= 2:
        pair_ranks = {rank for rank, cnt in board_rank_counts.items() if cnt == 2}
        if any(rank in pair_ranks for rank, _ in hole_cards):
            blockers.append("full_house_blocker")

    seen: set[str] = set()
    ordered: list[str] = []
    for blk in blockers:
        if blk not in seen:
            ordered.append(blk)
            seen.add(blk)
    return ordered


__all__ = [
    "analyze_river_context",
    "apply_river_no_bet_adjustment",
    "apply_river_facing_adjustment",
]
