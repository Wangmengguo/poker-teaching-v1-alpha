# poker_core/analysis.py
from __future__ import annotations

from typing import Any

from poker_core.suggest.codes import SCodes, mk_note

from .cards import get_rank_value, parse_card


# --- 基础特征提取 ---
def _hole_features(cards: list[str]) -> dict[str, Any]:
    assert len(cards) == 2, "need exactly 2 cards"
    r1, s1 = parse_card(cards[0])
    r2, s2 = parse_card(cards[1])
    v1, v2 = get_rank_value(r1), get_rank_value(r2)
    hi, lo = max(v1, v2), min(v1, v2)
    pair = r1 == r2
    suited = s1 == s2
    gap = abs(v1 - v2) - 1
    has_ace = (v1 == 14) or (v2 == 14)
    is_broadway = hi >= 10 and lo >= 10  # 两张牌都是broadway牌（TJQKA）
    return {
        "pair": pair,
        "suited": suited,
        "gap": gap,
        "high": hi,
        "low": lo,
        "has_ace": has_ace,
        "is_broadway": bool(is_broadway),
    }


def _derive_tags(feat: dict[str, Any]) -> tuple[set[str], str]:
    tags: set[str] = set()
    if feat["pair"]:
        tags.add("pair")
    if feat["suited"]:
        tags.add("suited")
    if feat["is_broadway"]:
        tags.add("broadway")
        if feat["suited"]:
            tags.add("suited_broadway")
        else:
            tags.add("broadway_offsuit")
    if feat["has_ace"] and feat["suited"]:
        tags.add("Ax_suited")

    # 兜底弱牌标签（可按你原规则继续扩展）
    if (
        "suited_broadway" not in tags
        and "pair" not in tags
        and "Ax_suited" not in tags
        and "broadway_offsuit" not in tags
    ):
        tags.add("weak")

    # hand_class 供策略快速判定（优先级：pair > Ax_suited > suited_broadway > broadway_offsuit > weak）
    if "pair" in tags:
        hand_class = "pair"
    elif "Ax_suited" in tags:
        hand_class = "Ax_suited"
    elif "suited_broadway" in tags:
        hand_class = "suited_broadway"
    elif "broadway_offsuit" in tags:
        hand_class = "broadway_offsuit"
    else:
        hand_class = "weak"

    return tags, hand_class


def classify_starting_hand(cards: list[str]) -> dict[str, Any]:
    feat = _hole_features(cards)
    tags, hand_class = _derive_tags(feat)

    # 兼容你原有 category 口径（可逐步废弃，仅保留展示）
    if feat["pair"] and feat["high"] >= 11:
        category = "premium_pair"
    elif (feat["suited"] and feat["is_broadway"] and feat["high"] >= 12) or (
        feat["pair"] and feat["high"] >= 10
    ):
        category = "strong"
    elif feat["suited"] and feat["gap"] <= 1 and feat["high"] >= 10:
        category = "speculative"
    elif "broadway_offsuit" in tags:
        category = "broadway_offsuit"
    elif (feat["high"] < 10) and (not feat["suited"]) and (feat["gap"] >= 3):
        category = "weak_offsuit"
    else:
        category = "weak"

    return {
        "pair": feat["pair"],
        "suited": feat["suited"],
        "gap": feat["gap"],
        "high": feat["high"],
        "low": feat["low"],
        "has_ace": feat["has_ace"],
        "is_broadway": feat["is_broadway"],
        "tags": sorted(list(tags)),
        "hand_class": hand_class,
        "category": category,
    }


def annotate_player_hand(cards: list[str]) -> dict[str, Any]:
    info = classify_starting_hand(cards)
    notes = []
    if "weak" in info["tags"]:
        notes.append(mk_note(SCodes.AN_WEAK))
    if info["category"] == "weak_offsuit":
        notes.append(mk_note(SCodes.AN_VERY_WEAK))
    if "suited_broadway" in info["tags"]:
        notes.append(mk_note(SCodes.AN_SUITED_BROADWAY))
    if info["suited"] and info["gap"] <= 1 and info["low"] >= 9:
        notes.append(mk_note(SCodes.AN_SUITED_CONNECTED))
    if info["hand_class"] == "pair" and info["high"] >= 11:
        notes.append(mk_note(SCodes.AN_PREMIUM_PAIR))
    return {"info": info, "notes": notes}


# --- 策略可调用的语义化助手（可选） ---
OPEN_RANGE_TAGS = {"pair", "suited_broadway", "Ax_suited", "broadway_offsuit"}
CALL_RANGE_TAGS = {"pair", "suited_broadway", "Ax_suited", "broadway_offsuit"}


def in_open_range(info: dict[str, Any]) -> bool:
    tags = set(info.get("tags", []))
    return bool(tags & OPEN_RANGE_TAGS)


def in_call_range(info: dict[str, Any]) -> bool:
    tags = set(info.get("tags", []))
    return bool(tags & CALL_RANGE_TAGS)


# --- 适配器：与文档口径对齐（从 gs 取两张牌） ---
def annotate_player_hand_from_gs(gs, actor: int) -> dict[str, Any]:
    hole = list(getattr(gs.players[actor], "hole", []) or [])
    if len(hole) != 2:
        return {
            "info": {"tags": ["unknown"], "hand_class": "unknown"},
            "notes": [mk_note(SCodes.WARN_ANALYSIS_MISSING)],
        }
    return annotate_player_hand(hole)
