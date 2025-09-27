from poker_core.suggest.node_key import node_key_from_observation
from poker_core.suggest.types import Observation


def _make_obs(**kwargs) -> Observation:
    base = dict(
        hand_id="nk1",
        actor=0,
        street="flop",
        bb=50,
        pot=300,
        to_call=0,
        acts=[],
        tags=["pair"],
        hand_class="value_two_pair_plus",
        table_mode="HU",
        spr_bucket="ge6",
        board_texture="dry",
        ip=True,
        first_to_act=False,
        last_to_act=False,
        pot_now=300,
        combo="AhKh",
        last_bet=0,
        role="pfr",
        range_adv=True,
        nut_adv=False,
        facing_size_tag="na",
        pot_type="single_raised",
        last_aggressor=None,
    )
    base.update(kwargs)
    return Observation(**base)


def test_node_key_components():
    obs = _make_obs(board_texture="semi", spr_bucket="3to6", ip=False, role="caller")
    key = node_key_from_observation(obs)

    parts = key.split("|")
    assert parts[0] == "flop"
    assert "single_raised" in parts
    assert "caller" in parts
    assert "oop" in parts
    assert any(part.startswith("texture=") and part.endswith("semi") for part in parts)
    assert any(part.startswith("spr=") and part.endswith("spr4") for part in parts)
    assert key.endswith("hand=value_two_pair_plus")


def test_node_key_stable_for_same_obs():
    obs = _make_obs()
    first = node_key_from_observation(obs)
    second = node_key_from_observation(_make_obs())
    assert first == second
