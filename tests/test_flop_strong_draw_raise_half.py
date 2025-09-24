from __future__ import annotations

from poker_core.domain.actions import LegalAction
from poker_core.suggest.context import SuggestContext, SuggestFlags, SuggestProfile
from poker_core.suggest.hand_strength import HandStrength
from poker_core.suggest.policy import policy_flop_v1
from poker_core.suggest.types import Observation, PolicyConfig
from poker_core.suggest.utils import HC_STRONG_DRAW


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
        tags=["suited_connector"],
        hand_class="weak_draw_or_air",
        table_mode="HU",
        button=0,
        spr_bucket="le3",
        board_texture="wet",
        ip=True,
        first_to_act=False,
        last_to_act=True,
        pot_now=450,
        combo="JTs",
        hand_strength=HandStrength("flop", "flop_strong_draw", HC_STRONG_DRAW),
        role="caller",
        range_adv=False,
        nut_adv=False,
        facing_size_tag="half",
        pot_type="threebet",
        last_aggressor=1,
        context=_ctx(),
    )
    defaults.update(kwargs)
    return Observation(**defaults)


def test_strong_draw_vs_half_triggers_raise():
    acts = [
        LegalAction("fold"),
        LegalAction("call", to_call=150),
        LegalAction("raise", min=550, max=1500),
    ]
    obs = _obs(
        acts=acts,
        to_call=150,
        hand_class=HC_STRONG_DRAW,
    )

    suggested, rationale, policy_name, meta = policy_flop_v1(obs, PolicyConfig())

    assert suggested["action"] == "raise"
    assert meta["size_tag"] == "half"
    assert any(r.get("code") == "FL_RAISE_SEMI_BLUFF" for r in rationale)
    assert policy_name == "flop_v1"


def test_non_strong_draw_vs_half_does_not_raise():
    acts = [
        LegalAction("fold"),
        LegalAction("call", to_call=150),
        LegalAction("raise", min=550, max=1500),
    ]
    obs = _obs(
        acts=acts,
        to_call=150,
        hand_class="weak_draw_or_air",
        hand_strength=HandStrength("flop", "flop_air", "weak_draw_or_air"),
    )

    suggested, rationale, policy_name, meta = policy_flop_v1(obs, PolicyConfig())

    assert suggested["action"] == "call"
    assert meta["size_tag"] in {None, "half"}
    assert any(r.get("code") == "FL_MDF_DEFEND" for r in rationale)
    assert policy_name == "flop_v1"
