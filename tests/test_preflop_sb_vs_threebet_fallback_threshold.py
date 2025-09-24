from __future__ import annotations

from poker_core.domain.actions import LegalAction
from poker_core.suggest.context import SuggestContext, SuggestFlags, SuggestProfile
from poker_core.suggest.hand_strength import HandStrength
from poker_core.suggest.policy_preflop import PreflopDecision, decide_sb_vs_threebet
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
    base_vs = {
        "SB_vs_BB_3bet": {
            "small": {
                "fourbet": {"AKs"},
                "call": {"A5s"},
            },
            "mid": {
                "fourbet": {"AKs"},
                "call": {"KQs"},
            },
        }
    }
    return SuggestContext(
        modes=overrides.get("modes", base_modes),
        open_table=overrides.get("open_table", {"SB": {"AKs"}}),
        vs_table=overrides.get("vs_table", base_vs),
        versions=overrides.get("versions", {"open": 1, "vs": 1, "modes": 1}),
        flags=overrides.get("flags", SuggestFlags(enable_flop_value_raise=True)),
        profile=overrides.get(
            "profile",
            SuggestProfile(strategy_name="medium", config_profile="builtin"),
        ),
    )


def _obs(**kwargs) -> Observation:
    defaults = dict(
        hand_id="h1",
        actor=0,
        street="preflop",
        bb=50,
        pot=300,
        to_call=0,
        acts=[],
        tags=["offsuit_misc"],
        hand_class="offsuit_misc",
        table_mode="HU",
        button=1,
        spr_bucket="na",
        board_texture="na",
        ip=False,
        first_to_act=False,
        last_to_act=False,
        pot_now=0,
        combo="72o",
        hand_strength=HandStrength("preflop", "preflop_unknown", "72o"),
        role="na",
        range_adv=False,
        nut_adv=False,
        facing_size_tag="na",
        pot_type="single_raised",
        last_aggressor=None,
    )
    defaults.update(kwargs)
    return Observation(**defaults)


def _acts(*entries: LegalAction) -> list[LegalAction]:
    return list(entries)


def test_sb_vs_threebet_fallback_calls_when_price_is_good():
    ctx = _ctx()
    cfg = PolicyConfig()
    acts = _acts(
        LegalAction("fold"),
        LegalAction("call", to_call=150),
    )
    obs = _obs(
        acts=acts,
        to_call=150,
        pot_now=450,
        pot=450,
    )

    result = decide_sb_vs_threebet(obs, ctx, cfg)
    assert isinstance(result, PreflopDecision)

    suggested, meta, rationale = result.resolve(obs, acts, cfg)
    assert suggested["action"] == "call"
    assert meta["bucket"] == "small"
    assert meta["pot_odds"] == round(150 / (450 + 150), 4)
    codes = {r["code"] for r in rationale}
    assert "PF_DEFEND_PRICE_OK" in codes


def test_sb_vs_threebet_fallback_folds_when_price_is_poor():
    ctx = _ctx()
    cfg = PolicyConfig()
    acts = _acts(
        LegalAction("fold"),
        LegalAction("call", to_call=350),
    )
    obs = _obs(
        acts=acts,
        to_call=350,
        pot_now=450,
        pot=450,
    )

    result = decide_sb_vs_threebet(obs, ctx, cfg)
    assert isinstance(result, PreflopDecision)

    suggested, _meta, rationale = result.resolve(obs, acts, cfg)
    assert suggested["action"] == "fold"
    codes = {r["code"] for r in rationale}
    assert "PF_FOLD_EXPENSIVE" in codes


def test_sb_vs_threebet_fallback_calls_tiny_threebet_even_if_price_high():
    ctx = _ctx()
    cfg = PolicyConfig()
    acts = _acts(
        LegalAction("fold"),
        LegalAction("call", to_call=100),
    )
    obs = _obs(
        acts=acts,
        to_call=100,
        pot_now=80,
        pot=180,
    )

    result = decide_sb_vs_threebet(obs, ctx, cfg)
    assert isinstance(result, PreflopDecision)

    suggested, meta, rationale = result.resolve(obs, acts, cfg)
    assert suggested["action"] == "call"
    assert meta["bucket"] == "small"
    codes = {r["code"] for r in rationale}
    assert "PF_DEFEND_PRICE_OK" in codes
