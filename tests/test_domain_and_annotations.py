import pytest
from poker_core.analysis import annotate_player_hand

# from packages.poker_core.deal import deal_hand
# from packages.poker_core.analysis import annotate_player_hand
from poker_core.deal import deal_hand


def test_players_range_assertion():
    with pytest.raises(AssertionError):
        deal_hand(seed=1, num_players=1)
    with pytest.raises(AssertionError):
        deal_hand(seed=1, num_players=7)


def test_seed_reproducible_annotations():
    a = deal_hand(seed=123, num_players=2)
    b = deal_hand(seed=123, num_players=2)
    anns_a = [annotate_player_hand(p["hole"]) for p in a["players"]]
    anns_b = [annotate_player_hand(p["hole"]) for p in b["players"]]
    assert anns_a == anns_b
