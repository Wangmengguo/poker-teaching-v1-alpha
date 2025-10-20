import pytest
from poker_core.domain.actions import LegalAction
from poker_core.suggest.policy import policy_flop_v1
from poker_core.suggest.policy import policy_river_v1
from poker_core.suggest.types import Observation
from poker_core.suggest.types import PolicyConfig


def _obs_postflop(**kw):
    defaults = dict(
        hand_id="h_def",
        actor=0,
        street="flop",
        bb=50,
        pot=0,
        pot_now=0,
        to_call=0,
        acts=[],
        tags=[],
        hand_class="weak_draw_or_air",
        table_mode="HU",
        button=1,  # actor=0 OOP by default postflop in HU
        spr_bucket="mid",
        board_texture="dry",
        ip=False,
        role="pfr",
        facing_size_tag="na",
        pot_type="single_raised",
        last_aggressor=None,
        hole=(),
        board=(),
    )
    defaults.update(kw)
    return Observation(**defaults)  # type: ignore


@pytest.fixture(autouse=True)
def _enable_defense(monkeypatch):
    monkeypatch.setenv("SUGGEST_DEFENSE_V1", "1")
    monkeypatch.setenv("SUGGEST_EXTENDED_FACING", "1")
    yield
    # pytest will restore env via monkeypatch


def test_flop_overbet_strong_value_calls():
    # pot_now=200, to_call=300 → r=1.5 (overbet_1.5x), pot_odds=0.6 ≤ 0.86 → call
    acts = [
        LegalAction(action="call", to_call=300),
        LegalAction(action="fold"),
    ]
    obs = _obs_postflop(
        street="flop", acts=acts, pot_now=200, to_call=300, hand_class="value_two_pair_plus"
    )
    suggested, rationale, policy, meta = policy_flop_v1(obs, PolicyConfig())
    assert policy == "flop_v1"
    assert suggested["action"] == "call"


def test_flop_overbet_strong_draw_folds():
    # pot_now=200, to_call=300 → r=1.5 (overbet_1.5x), pot_odds=0.6 > 0.55 → fold
    acts = [
        LegalAction(action="call", to_call=300),
        LegalAction(action="fold"),
    ]
    obs = _obs_postflop(
        street="flop", acts=acts, pot_now=200, to_call=300, hand_class="strong_draw"
    )
    suggested, rationale, policy, meta = policy_flop_v1(obs, PolicyConfig())
    assert policy == "flop_v1"
    assert suggested["action"] == "fold"


def test_river_medium_value_pot_calls():
    # pot_now=100, to_call=100 → r=1.0 (pot), pot_odds=0.5 ≤ 0.70 → call
    acts = [
        LegalAction(action="call", to_call=100),
        LegalAction(action="fold"),
    ]
    obs = _obs_postflop(
        street="river",
        acts=acts,
        pot_now=100,
        to_call=100,
        hand_class="top_pair_weak_or_second_pair",
    )
    # river defense uses value tiers; simulate via semantics fallback by class mapping in defense thresholds
    suggested, rationale, policy, meta = policy_river_v1(obs, PolicyConfig())
    assert policy == "river_v1"
    assert suggested["action"] == "call"


def test_overbet_huge_air_folds_on_flop():
    # pot_now=200, to_call=700 → r=3.5 (overbet_huge), pot_odds=700/(900)=0.777... → fold for air
    acts = [
        LegalAction(action="call", to_call=700),
        LegalAction(action="fold"),
    ]
    obs = _obs_postflop(
        street="flop", acts=acts, pot_now=200, to_call=700, hand_class="weak_draw_or_air"
    )
    suggested, rationale, policy, meta = policy_flop_v1(obs, PolicyConfig())
    assert policy == "flop_v1"
    assert suggested["action"] == "fold"
