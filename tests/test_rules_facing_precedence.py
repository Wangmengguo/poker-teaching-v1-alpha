import os

import pytest
from poker_core.domain.actions import LegalAction
from poker_core.suggest.policy import policy_flop_v1
from poker_core.suggest.policy import policy_river_v1
from poker_core.suggest.types import Observation
from poker_core.suggest.types import PolicyConfig


def _obs(**kw):
    d = dict(
        hand_id="h_rule",
        actor=0,
        street="flop",
        bb=50,
        pot=0,
        pot_now=0,
        to_call=0,
        acts=[],
        tags=[],
        hand_class="value_two_pair_plus",
        table_mode="HU",
        button=1,
        spr_bucket="le3",
        board_texture="dry",
        ip=False,
        role="pfr",
        facing_size_tag="third",
        pot_type="single_raised",
        last_aggressor=None,
        hole=(),
        board=(),
    )
    d.update(kw)
    return Observation(**d)  # type: ignore


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SUGGEST_DEFENSE_V1", "1")
    monkeypatch.setenv("SUGGEST_EXTENDED_FACING", "1")
    yield


def test_flop_rules_facing_value_raise_precedence():
    # Use rule path in flop_rules_HU_medium.json → value_two_pair_plus facing.third → raise half
    acts = [
        LegalAction(action="raise", min=100, max=1000),
        LegalAction(action="call", to_call=50),
        LegalAction(action="fold"),
    ]
    obs = _obs(
        street="flop",
        acts=acts,
        pot_now=150,
        to_call=50,
        hand_class="value_two_pair_plus",
        spr_bucket="3to6",
    )
    suggested, rationale, policy, meta = policy_flop_v1(obs, PolicyConfig())
    assert policy == "flop_v1"
    # JSON facing should take precedence and choose raise
    assert suggested["action"] == "raise"


def test_flop_rules_loose_pfr_ip_value_raise():
    # loose: value_two_pair_plus ip/dry/3to6 facing.third → raise two_third
    acts = [
        LegalAction(action="raise", min=100, max=1000),
        LegalAction(action="call", to_call=50),
        LegalAction(action="fold"),
    ]
    obs = _obs(
        street="flop",
        acts=acts,
        pot_now=150,
        to_call=50,
        hand_class="value_two_pair_plus",
        spr_bucket="3to6",
    )
    # ensure we run with loose strategy
    os.environ["SUGGEST_STRATEGY"] = "loose"
    suggested, rationale, policy, meta = policy_flop_v1(obs, PolicyConfig())
    assert policy == "flop_v1"
    assert suggested["action"] == "raise"
    os.environ.pop("SUGGEST_STRATEGY", None)


def test_flop_rules_tight_pfr_ip_value_small_raise_or_call():
    # tight: value_two_pair_plus ip/dry/le3 facing.third → raise half；facing.half → call_le 0.65
    acts = [
        LegalAction(action="raise", min=100, max=1000),
        LegalAction(action="call", to_call=100),
        LegalAction(action="fold"),
    ]
    # half facing (to_call/pot_now≈0.67 → denom=150+100=250, pot_odds=0.4 ≤ 0.65 → call)
    obs = _obs(
        street="flop",
        acts=acts,
        pot_now=150,
        to_call=100,
        hand_class="value_two_pair_plus",
        spr_bucket="le3",
    )
    os.environ["SUGGEST_STRATEGY"] = "tight"
    suggested, rationale, policy, meta = policy_flop_v1(obs, PolicyConfig())
    assert suggested["action"] == "call"
    os.environ.pop("SUGGEST_STRATEGY", None)


def test_river_rules_facing_medium_value_mix_window():
    # river_rules_HU_medium.json medium_value facing.pot → call_le 0.70, mix_to 0.75
    acts = [
        LegalAction(action="call", to_call=150),
        LegalAction(action="fold"),
    ]
    # pot_now=200 → pot_odds = 150/(350) ≈ 0.428 → far below call_le
    obs = _obs(
        street="river",
        acts=acts,
        pot_now=200,
        to_call=150,
        hand_class="top_pair_weak_or_second_pair",
    )
    suggested, rationale, policy, meta = policy_river_v1(obs, PolicyConfig())
    assert policy == "river_v1"
    assert suggested["action"] == "call"
