"""Derive canonical node keys for runtime policies."""

from __future__ import annotations

from typing import Any

from .classifiers import canonical_texture_from_alias
from .classifiers import classify_board_texture
from .classifiers import classify_spr_bin
from .types import Observation


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

    hand_class = _slug(getattr(obs, "hand_class", "unknown")) or "unknown"

    parts = [
        street,
        pot_type,
        role,
        position,
        f"texture={texture}",
        f"spr={spr_label}",
        f"hand={hand_class}",
    ]
    return "|".join(parts)


__all__ = [
    "classify_board_texture",
    "classify_spr_bin",
    "node_key_from_observation",
]
