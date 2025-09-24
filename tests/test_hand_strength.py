import pytest
from poker_core.suggest.hand_strength import derive_hand_strength
from poker_core.suggest.utils import (
    HC_MID_OR_THIRD_MINUS,
    HC_OP_TPTK,
    HC_STRONG_DRAW,
    HC_VALUE,
    HC_WEAK_OR_AIR,
)


@pytest.mark.parametrize(
    "tags,expected",
    [
        ([], "preflop_unknown"),
        (["Ax_suited"], "preflop_ax_suited"),
        (["suited_broadway", "Ax_suited"], "preflop_suited_broadway"),
        (["pair", "suited_broadway"], "preflop_pair"),
        (["broadway_offsuit"], "preflop_broadway_offsuit"),
    ],
)
def test_preflop_tags_priority(tags, expected):
    hs = derive_hand_strength("preflop", tags, hand_class="AKs")
    assert hs.street == "preflop"
    assert hs.label == expected
    assert hs.raw == "AKs"


@pytest.mark.parametrize(
    "hand_class,expected",
    [
        (HC_VALUE, "flop_value"),
        (HC_OP_TPTK, "flop_top_pair_or_overpair"),
        (HC_STRONG_DRAW, "flop_strong_draw"),
        (HC_MID_OR_THIRD_MINUS, "flop_mid_or_weak"),
        (HC_WEAK_OR_AIR, "flop_air"),
        ("unknown_label", "flop_unknown"),
    ],
)
def test_flop_hand_class_mapping(hand_class, expected):
    hs = derive_hand_strength("flop", ["any"], hand_class=hand_class)
    assert hs.street == "flop"
    assert hs.label == expected
    assert hs.raw == hand_class
