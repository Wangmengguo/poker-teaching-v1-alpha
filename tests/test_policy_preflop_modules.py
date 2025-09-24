from __future__ import annotations

from poker_core.domain.actions import LegalAction
from poker_core.suggest.context import SuggestContext, SuggestFlags, SuggestProfile
from poker_core.suggest.hand_strength import HandStrength
from poker_core.suggest.policy_preflop import (
    PreflopDecision,
    decide_bb_defend,
    decide_sb_open,
    decide_sb_vs_threebet,
)
from poker_core.suggest.types import Observation, PolicyConfig


def _ctx(**overrides) -> SuggestContext:
    base_modes = {
        "HU": {
            "open_bb": 2.5,
            "defend_threshold_ip": 0.42,
            "defend_threshold_oop": 0.38,
            "reraise_ip_mult": 3.0,
            "reraise_oop_mult": 3.5,
            "reraise_oop_offset": 0.5,
            "cap_ratio": 0.9,
            "fourbet_ip_mult": 2.2,
            "cap_ratio_4b": 0.85,
        }
    }
    base_open = {"SB": {"AKs"}, "BB": set()}
    base_vs = {
        "BB_vs_SB": {
            "small": {
                "call": {"A5s"},
                "reraise": {"AKs"},
            }
        },
        "SB_vs_BB_3bet": {
            "small": {
                "fourbet": {"AKs"},
                "call": {"A5s"},
            }
        },
    }
    return SuggestContext(
        modes=overrides.get("modes", base_modes),
        open_table=overrides.get("open_table", base_open),
        vs_table=overrides.get("vs_table", base_vs),
        versions=overrides.get("versions", {"open": 1, "vs": 1, "modes": 1}),
        flags=overrides.get(
            "flags",
            SuggestFlags(enable_flop_value_raise=True),
        ),
        profile=overrides.get(
            "profile",
            SuggestProfile(strategy_name="medium", config_profile="builtin"),
        ),
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
        button=1,
        spr_bucket="na",
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
    )
    defaults.update(kwargs)
    return Observation(**defaults)


def _acts(*entries: LegalAction) -> list[LegalAction]:
    return list(entries)


def test_sb_open_in_range_raises():
    ctx = _ctx()
    acts = _acts(
        LegalAction("fold"),
        LegalAction("check"),
        LegalAction("raise", min=100, max=400),
    )
    obs = _obs(acts=acts, to_call=0, first_to_act=True, last_to_act=False)
    cfg = PolicyConfig()

    result = decide_sb_open(obs, ctx, cfg)
    assert isinstance(result, PreflopDecision)
    suggested, meta, rationale = result.resolve(obs, acts, cfg)
    assert suggested["action"] == "raise"
    assert suggested["amount"] == 125  # 2.5 * 50
    codes = {r["code"] for r in rationale}
    assert "PF_OPEN_RANGE_HIT" in codes
    assert meta["open_bb"] == 2.5


def test_bb_defend_prefers_3bet_when_in_reraise_bucket():
    ctx = _ctx()
    acts = _acts(
        LegalAction("fold"),
        LegalAction("call", to_call=50),
        LegalAction("raise", min=250, max=600),
    )
    obs = _obs(
        actor=1,
        to_call=50,
        pot=200,
        pot_now=300,
        acts=acts,
        combo="AKs",
        ip=False,
        first_to_act=False,
        last_to_act=True,
        pot_type="single_raised",
    )
    cfg = PolicyConfig()

    result = decide_bb_defend(obs, ctx, cfg)
    assert isinstance(result, PreflopDecision)
    suggested, meta, rationale = result.resolve(obs, acts, cfg)
    assert suggested["action"] == "raise"
    assert suggested["amount"] == 300  # 6bb to-amount by default params
    codes = {r["code"] for r in rationale}
    assert "PF_DEFEND_3BET" in codes
    assert meta["bucket"] == "small"


def test_sb_vs_threebet_fourbet_enabled():
    ctx = _ctx()
    acts = _acts(
        LegalAction("fold"),
        LegalAction("call", to_call=325),
        LegalAction("raise", min=900, max=2200),
    )
    obs = _obs(
        actor=0,
        to_call=325,
        pot=250,
        pot_now=575,
        acts=acts,
        combo="AKs",
        ip=False,
        first_to_act=False,
        last_to_act=False,
        pot_type="single_raised",
        spr_bucket="high",
    )
    cfg = PolicyConfig()

    result = decide_sb_vs_threebet(obs, ctx, cfg)
    assert isinstance(result, PreflopDecision)
    suggested, meta, rationale = result.resolve(obs, acts, cfg)
    assert suggested["action"] == "raise"
    # 9bb threebet_to * 2.2 ≈ 19.8 → round 20 bb
    assert suggested["amount"] == 1000
    codes = {r["code"] for r in rationale}
    assert "PF_ATTACK_4BET" in codes
    assert meta["fourbet_to_bb"] == 20
