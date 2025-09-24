# tests/test_analysis_tags.py
import pytest
from poker_core.analysis import classify_starting_hand


@pytest.mark.parametrize(
    "cards, expect_tags, hand_class",
    [
        (["Ah", "Kh"], {"suited_broadway", "Ax_suited"}, "Ax_suited"),
        (["Qs", "Js"], {"suited_broadway"}, "suited_broadway"),
        (["Ad", "5d"], {"Ax_suited"}, "Ax_suited"),
        (["9c", "9d"], {"pair"}, "pair"),
        (["Tc", "9d"], {"weak"}, "weak"),
    ],
)
def test_tags(cards, expect_tags, hand_class):
    info = classify_starting_hand(cards)
    assert set(info["tags"]) & expect_tags
    assert info["hand_class"] == hand_class
