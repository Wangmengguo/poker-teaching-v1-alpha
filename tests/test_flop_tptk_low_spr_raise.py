from __future__ import annotations

from poker_core.domain.actions import LegalAction
from poker_core.suggest.context import SuggestContext, SuggestFlags, SuggestProfile
from poker_core.suggest.hand_strength import HandStrength
from poker_core.suggest.policy import policy_flop_v1
from poker_core.suggest.types import Observation, PolicyConfig
from poker_core.suggest.utils import HC_OP_TPTK


def _ctx() -> SuggestContext:
    return SuggestContext(
        modes={"HU": {"postflop_cap_ratio": 0.85}},
        open_table={},
        vs_table={},
        versions={"open": 1, "vs": 1, "modes": 1},
        flags=SuggestFlags(enable_flop_value_raise=True),
        profile=SuggestProfile(strategy_name="medium", config_profile="builtin"),
    )


def _obs(**kwargs) -> Observation:
    defaults = dict(
        hand_id="h",
        actor=0,
        street="flop",
        bb=50,
        pot=300,
        to_call=0,
        acts=[],
        tags=["offsuit_broadway"],
        hand_class="weak_draw_or_air",
        table_mode="HU",
        button=0,
        spr_bucket="le3",
        board_texture="dry",
        ip=True,
        first_to_act=False,
        last_to_act=True,
        pot_now=300,
        combo="AQo",
        hand_strength=HandStrength("flop", "flop_top_pair_or_overpair", HC_OP_TPTK),
        role="pfr",
        range_adv=True,
        nut_adv=False,
        facing_size_tag="third",
        pot_type="single_raised",
        last_aggressor=0,
        context=_ctx(),
    )
    defaults.update(kwargs)
    return Observation(**defaults)


def test_low_spr_tptk_faces_small_size_raises():
    acts = [
        LegalAction("fold"),
        LegalAction("call", to_call=100),
        LegalAction("raise", min=400, max=1200),
    ]
    obs = _obs(
        acts=acts,
        to_call=100,
        hand_class=HC_OP_TPTK,
        pot_now=300,
    )

    suggested, rationale, policy_name, meta = policy_flop_v1(obs, PolicyConfig())

    assert suggested["action"] == "raise"
    assert meta["size_tag"] == "two_third"
    assert any(r.get("code") == "FL_RAISE_VALUE" for r in rationale)
    assert policy_name == "flop_v1"


def test_mid_spr_tptk_keeps_call_plan():
    acts = [
        LegalAction("fold"),
        LegalAction("call", to_call=100),
        LegalAction("raise", min=400, max=1200),
    ]
    obs = _obs(
        acts=acts,
        to_call=100,
        hand_class=HC_OP_TPTK,
        spr_bucket="mid",
        hand_strength=HandStrength("flop", "flop_top_pair_or_overpair", HC_OP_TPTK),
    )

    suggested, rationale, policy_name, meta = policy_flop_v1(obs, PolicyConfig())

    assert suggested["action"] == "call"
    assert meta["size_tag"] in {None, "third"}
    assert any(r.get("code") == "FL_MDF_DEFEND" for r in rationale)
    assert policy_name == "flop_v1"
