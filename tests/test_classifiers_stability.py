from poker_core.suggest.node_key import classify_board_texture
from poker_core.suggest.node_key import classify_spr_bin


def test_texture_classifier_matches_thresholds():
    # Pair or three-suited boards map to wet
    assert classify_board_texture(["Ah", "Ad", "7c"]) == "wet"
    assert classify_board_texture(["Kh", "Qh", "2h"]) == "wet"

    # Two suited or gap-connected boards map to semi
    assert classify_board_texture(["Ah", "Kh", "2c"]) == "semi"
    assert classify_board_texture(["9s", "7h", "8d"]) == "semi"

    # Dry baseline when thresholds unmet
    assert classify_board_texture(["Ah", "7c", "2d"]) == "dry"


def test_spr_classifier_respects_boundaries_and_aliases():
    # Exact boundaries should fall into right-closed intervals
    assert classify_spr_bin(3.0, None) == "spr4"
    assert classify_spr_bin(5.0, None) == "spr6"
    assert classify_spr_bin(7.0, None) == "spr8"
    assert classify_spr_bin(9.0, None) == "spr10"

    # Aliases from existing buckets remain stable
    assert classify_spr_bin(None, "le3") == "spr2"
    assert classify_spr_bin(None, "3to6") == "spr4"
    assert classify_spr_bin(None, "ge6") == "spr6"
    assert classify_spr_bin(None, "high") == "spr6"

    # Unknown values fall back to 'na'
    assert classify_spr_bin(None, None) == "na"
