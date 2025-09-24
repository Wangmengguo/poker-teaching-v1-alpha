"""Unified hand strength labels across streets."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .utils import (
    HC_MID_OR_THIRD_MINUS,
    HC_OP_TPTK,
    HC_STRONG_DRAW,
    HC_VALUE,
    HC_WEAK_OR_AIR,
)


@dataclass(frozen=True)
class HandStrength:
    street: str
    label: str
    raw: str


_PREFLOP_PRIORITY = [
    "pair",
    "suited_broadway",
    "broadway_offsuit",
    "Ax_suited",
]

_PREFLOP_TAG_LABEL = {
    "pair": "preflop_pair",
    "suited_broadway": "preflop_suited_broadway",
    "broadway_offsuit": "preflop_broadway_offsuit",
    "Ax_suited": "preflop_ax_suited",
}

_FLOP_LABELS = {
    HC_VALUE: "flop_value",
    HC_OP_TPTK: "flop_top_pair_or_overpair",
    HC_STRONG_DRAW: "flop_strong_draw",
    HC_MID_OR_THIRD_MINUS: "flop_mid_or_weak",
    HC_WEAK_OR_AIR: "flop_air",
}


def derive_hand_strength(street: str, tags: Iterable[str], hand_class: str) -> HandStrength:
    st = (street or "preflop").lower()
    raw = str(hand_class or "unknown")

    if st == "flop":
        label = _FLOP_LABELS.get(raw, "flop_unknown")
        return HandStrength(street="flop", label=label, raw=raw)

    tags_set = {str(t) for t in (tags or [])}
    for tag in _PREFLOP_PRIORITY:
        if tag in tags_set:
            return HandStrength(
                street="preflop",
                label=_PREFLOP_TAG_LABEL[tag],
                raw=raw,
            )
    return HandStrength(street="preflop", label="preflop_unknown", raw=raw)


__all__ = ["HandStrength", "derive_hand_strength"]
