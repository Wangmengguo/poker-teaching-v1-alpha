from __future__ import annotations

from poker_core.domain.actions import LegalAction
from poker_core.suggest.context import SuggestContext, SuggestFlags, SuggestProfile
from poker_core.suggest.hand_strength import HandStrength
from poker_core.suggest.policy import policy_flop_v1
from poker_core.suggest.types import Observation, PolicyConfig
from poker_core.suggest.utils import HC_OP_TPTK, HC_STRONG_DRAW, HC_VALUE


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
        tags=["offsuit_misc"],
        hand_class="weak_draw_or_air",
        table_mode="HU",
        button=0,
        spr_bucket="mid",
        board_texture="semi",
        ip=False,
        first_to_act=False,
        last_to_act=True,
        pot_now=400,
        combo="T8o",
        hand_strength=HandStrength("flop", "flop_air", "weak_draw_or_air"),
        role="caller",
        range_adv=False,
        nut_adv=False,
        facing_size_tag="two_third+",
        pot_type="single_raised",
        last_aggressor=0,
        context=_ctx(),
    )
    defaults.update(kwargs)
    return Observation(**defaults)


def test_facing_large_size_weak_class_prefers_fold():
    acts = [
        LegalAction("fold"),
        LegalAction("call", to_call=240),
    ]
    obs = _obs(
        acts=acts,
        to_call=240,
        pot_now=320,
    )

    suggested, rationale, policy_name, meta = policy_flop_v1(obs, PolicyConfig())

    assert suggested["action"] == "fold"
    assert policy_name == "flop_v1"
    assert meta["facing_size_tag"] == "two_third+"
    assert any(r.get("code") == "PL_FOLD" or r.get("code") == "PL_FOLD_POTODDS" for r in rationale)


def test_facing_large_size_strong_classes_not_forced_fold():
    acts = [
        LegalAction("fold"),
        LegalAction("call", to_call=240),
    ]
    for hand_class, strength_label in [
        (HC_VALUE, "flop_value"),
        (HC_OP_TPTK, "flop_top_pair_or_overpair"),
        (HC_STRONG_DRAW, "flop_strong_draw"),
    ]:
        obs = _obs(
            acts=acts,
            to_call=240,
            pot_now=320,
            hand_class=hand_class,
            hand_strength=HandStrength("flop", strength_label, hand_class),
        )

        suggested, rationale, policy_name, meta = policy_flop_v1(obs, PolicyConfig())

        assert suggested["action"] != "fold"
        assert policy_name == "flop_v1"
        assert meta["facing_size_tag"] == "two_third+"
        # should continue to respect MDF rationale for strong classes
        assert any(r.get("code") == "FL_MDF_DEFEND" for r in rationale)
