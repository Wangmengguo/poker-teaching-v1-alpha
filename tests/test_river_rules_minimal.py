from __future__ import annotations

from poker_core.domain.actions import LegalAction
from poker_core.suggest.hand_strength import HandStrength
from poker_core.suggest.policy import policy_river_v1
from poker_core.suggest.types import Observation
from poker_core.suggest.types import PolicyConfig


def _base_obs(**overrides):
    defaults = dict(
        hand_id="river_hand",
        actor=0,
        street="river",
        bb=50,
        pot=400,
        to_call=0,
        acts=[LegalAction("bet", min=50, max=400), LegalAction("check")],
        tags=["pair"],
        hand_class="pair",
        table_mode="HU",
        button=0,
        spr_bucket="mid",
        board_texture="dry",
        ip=True,
        first_to_act=True,
        last_to_act=False,
        pot_now=400,
        combo="",
        last_bet=100,
        hand_strength=HandStrength(street="river", label="river_unknown", raw=""),
        role="pfr",
        range_adv=False,
        nut_adv=False,
        facing_size_tag="na",
        pot_type="single_raised",
        last_aggressor=0,
        context=None,
    )
    defaults.update(overrides)
    return Observation(**defaults)


def test_value_threshold_and_blocker_logic():
    # Strong value hand without blockers should lean into thin value betting.
    obs_value = _base_obs(
        hole=("Ad", "Ac"),
        board=("Kh", "Qh", "7h", "2c", "2d"),
    )
    suggested, rationale, policy_name, meta = policy_river_v1(obs_value, PolicyConfig())
    assert policy_name == "river_v1"
    assert suggested["action"] == "bet"
    assert meta.get("size_tag") == "third"
    assert meta.get("river_value_tier") == "strong_value"
    assert not meta.get("river_blockers")

    # With the nut flush blocker, strategy should slow down and prefer checking/inducing.
    obs_blocker = _base_obs(
        hole=("Ah", "Ac"),
        board=("Kh", "Qh", "7h", "2c", "2d"),
    )
    suggested_b, rationale_b, policy_name_b, meta_b = policy_river_v1(obs_blocker, PolicyConfig())
    assert policy_name_b == "river_v1"
    assert suggested_b["action"] == "check"
    assert meta_b.get("river_value_tier") == "strong_value"
    assert meta_b.get("river_blockers") == ["nut_flush_blocker"]


def test_weak_showdown_prefers_check_or_fold():
    # Weak showdown strength should default to checking when uncontested.
    obs_weak = _base_obs(
        hole=("9d", "4c"),
        board=("Kh", "Qd", "7c", "2s", "2h"),
        tags=["weak"],
        hand_class="weak",
    )
    suggested, rationale, policy_name, meta = policy_river_v1(obs_weak, PolicyConfig())
    assert policy_name == "river_v1"
    assert suggested["action"] == "check"
    assert meta.get("river_value_tier") == "weak_showdown"

    # Facing a large bet, weak showdown holdings should lean toward folding.
    obs_facing = _base_obs(
        acts=[LegalAction("call", to_call=300), LegalAction("fold")],
        to_call=300,
        pot_now=200,
        facing_size_tag="two_third+",
        hole=("9d", "4c"),
        board=("Kh", "Qd", "7c", "2s", "2h"),
        tags=["weak"],
        hand_class="weak",
    )
    suggested_f, rationale_f, policy_name_f, meta_f = policy_river_v1(obs_facing, PolicyConfig())
    assert policy_name_f == "river_v1"
    assert suggested_f["action"] == "fold"
    assert meta_f.get("river_value_tier") == "weak_showdown"
