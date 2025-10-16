"""Derive canonical node keys for runtime policies."""

from __future__ import annotations

from typing import Any

from .classifiers import canonical_texture_from_alias
from .classifiers import classify_board_texture
from .classifiers import classify_spr_bin
from .types import Observation

_FACING_ALIASES = {
    "two_third": "two_third+",
    "two_third_plus": "two_third+",
    "twothird+": "two_third+",
    "third_pot": "third",
    "half_pot": "half",
}

_KNOWN_FACING = {"na", "third", "half", "two_third+"}


def canonical_facing_tag(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "na"
    if text in _KNOWN_FACING:
        return text
    alias = _FACING_ALIASES.get(text)
    if alias:
        return alias
    return "na"


# Map internal hand_class labels to table-friendly labels used by NPZ policies.
_HAND_ALIASES_POSTFLOP = {
    # 6-bucket → NPZ 8-bucket近似映射
    "overpair_or_top_pair_strong": "overpair_or_tptk",
    "top_pair_weak_or_second_pair": "top_pair_weak_or_second",
    "middle_pair_or_third_pair_minus": "middle_pair_or_third_minus",
    "weak_draw_or_air": "weak_draw",
}


def _canonical_hand_for_table(street: str, hand_class: Any) -> str:
    text = _slug(hand_class) or "unknown"
    st = (street or "").lower()
    if st in {"flop", "turn", "river"}:
        if text in _HAND_ALIASES_POSTFLOP:
            return _HAND_ALIASES_POSTFLOP[text]
    return text


def _slug(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in text)


def node_key_from_observation(obs: Observation) -> str:
    street = _slug(getattr(obs, "street", "preflop")) or "preflop"
    pot_type = _slug(getattr(obs, "pot_type", "single_raised")) or "single_raised"
    role = _slug(getattr(obs, "role", "na")) or "na"
    position = "ip" if bool(getattr(obs, "ip", False)) else "oop"

    texture = canonical_texture_from_alias(getattr(obs, "board_texture", None))
    if street == "preflop":
        texture = "na"

    spr_label = classify_spr_bin(None, getattr(obs, "spr_bucket", None))
    if street == "preflop":
        # Preflop 表约定不区分 SPR；保持 'spr=na' 以匹配 NPZ 键
        spr_label = "na"

    facing_raw = getattr(obs, "facing_size_tag", None)
    facing = canonical_facing_tag(facing_raw)

    hand_class = _canonical_hand_for_table(street, getattr(obs, "hand_class", "unknown"))

    parts = [
        street,
        pot_type,
        role,
        position,
        f"texture={texture}",
        f"spr={spr_label}",
        f"facing={facing}",
        f"hand={hand_class}",
    ]
    return "|".join(parts)


__all__ = [
    "classify_board_texture",
    "classify_spr_bin",
    "canonical_facing_tag",
    "node_key_from_observation",
]
