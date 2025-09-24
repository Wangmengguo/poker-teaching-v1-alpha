from __future__ import annotations

from poker_core.domain.actions import LegalAction
from poker_core.suggest.context import SuggestContext, SuggestFlags, SuggestProfile
from poker_core.suggest.decision import Decision, SizeSpec
from poker_core.suggest.hand_strength import HandStrength
from poker_core.suggest.types import Observation, PolicyConfig


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
        street="preflop",
        bb=50,
        pot=150,
        to_call=0,
        acts=[],
        tags=["suited_broadway"],
        hand_class="AKs",
        table_mode="HU",
        button=0,
        spr_bucket="mid",
        board_texture="na",
        ip=False,
        first_to_act=True,
        last_to_act=False,
        pot_now=150,
        combo="AKs",
        hand_strength=HandStrength("preflop", "preflop_suited_broadway", "AKs"),
        role="na",
        range_adv=False,
        nut_adv=False,
        facing_size_tag="na",
        pot_type="limped",
        last_aggressor=None,
        context=_ctx(),
    )
    defaults.update(kwargs)
    return Observation(**defaults)


def test_decision_bb_sizing_respects_min_reopen():
    decision = Decision(
        action="raise",
        sizing=SizeSpec.bb(3.0),
        meta={"open_bb": 3.0},
    )
    acts = [
        LegalAction("fold"),
        LegalAction("raise", min=160, max=400),
    ]
    obs = _obs(acts=acts, to_call=0)

    suggested, meta, rationale = decision.resolve(obs, acts, PolicyConfig())

    assert suggested == {"action": "raise", "amount": 160}
    assert meta["open_bb"] == 3.0
    assert any(r.get("code") == "FL_MIN_REOPEN_ADJUSTED" for r in rationale)


def test_decision_size_tag_to_amount():
    decision = Decision(
        action="bet",
        sizing=SizeSpec.tag("half"),
        meta={"size_tag": "half"},
    )
    acts = [
        LegalAction("bet", min=50, max=1000),
    ]
    obs = _obs(street="flop", pot=300, pot_now=300, acts=acts)

    suggested, meta, rationale = decision.resolve(obs, acts, PolicyConfig())

    assert suggested["amount"] == 150
    assert meta["size_tag"] == "half"
    assert rationale == []
