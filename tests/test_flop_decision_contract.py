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
        tags=["suited_broadway"],
        hand_class="value_two_pair_plus",
        table_mode="HU",
        button=0,
        spr_bucket="mid",
        board_texture="dry",
        ip=True,
        first_to_act=False,
        last_to_act=True,
        pot_now=300,
        combo="AKs",
        hand_strength=HandStrength("flop", "flop_value", "value_two_pair_plus"),
        role="pfr",
        range_adv=True,
        nut_adv=True,
        facing_size_tag="na",
        pot_type="single_raised",
        last_aggressor=0,
        context=_ctx(),
    )
    defaults.update(kwargs)
    return Observation(**defaults)


def test_flop_autobet_third_size_tag():
    acts = [
        LegalAction("check"),
        LegalAction("bet", min=50, max=1000),
    ]
    obs = _obs(acts=acts, to_call=0)

    suggested, rationale, policy_name, meta = policy_flop_v1(obs, PolicyConfig())

    assert suggested["action"] == "bet"
    assert suggested["amount"] == 100  # third pot
    assert meta["size_tag"] == "third"
    assert meta["plan"] in {None, ""} or isinstance(meta.get("plan"), str)
    assert policy_name == "flop_v1"


def test_flop_value_raise_vs_small_bet_min_reopen():
    acts = [
        LegalAction("call", to_call=100),
        LegalAction("raise", min=450, max=1200),
    ]
    # 调小 pot_now 以确保 raise_to 目标 < raise.min，从而触发最小提升
    obs = _obs(
        acts=acts,
        to_call=100,
        pot_now=200,
        facing_size_tag="third",
        last_to_act=True,
        spr_bucket="3to6",
    )

    suggested, rationale, policy_name, meta = policy_flop_v1(obs, PolicyConfig())

    assert suggested["action"] == "raise"
    # raise target < min → should be bumped to raise.min
    assert suggested["amount"] == 450
    assert meta["size_tag"] == "half"
    assert any(r.get("code") == "FL_MIN_REOPEN_ADJUSTED" for r in rationale)


def test_flop_rule_trace_in_meta():
    acts = [
        LegalAction("call", to_call=150),
        LegalAction("raise", min=600, max=1600),
    ]
    obs = _obs(
        acts=acts,
        to_call=150,
        pot_now=600,
        role="caller",
        ip=False,
        range_adv=False,
        nut_adv=True,
        facing_size_tag="half",
        spr_bucket="low",
        hand_class="value_two_pair_plus",
    )

    suggested, rationale, policy_name, meta = policy_flop_v1(obs, PolicyConfig())

    assert suggested["action"] in {"call", "raise"}
    assert "rule_path" in meta
    assert meta["rule_path"].startswith("single_raised/")


def test_flop_vs_half_default_call_includes_rule_path():
    acts = [
        LegalAction("call", to_call=150),
    ]
    obs = _obs(
        acts=acts,
        to_call=150,
        pot_now=600,
        facing_size_tag="half",
        hand_class="mid_or_third_minus",
        hand_strength=HandStrength("flop", "flop_mid_or_weak", "mid_or_third_minus"),
        nut_adv=False,
        range_adv=False,
    )

    suggested, rationale, policy_name, meta = policy_flop_v1(obs, PolicyConfig())

    assert suggested == {"action": "call"}
    assert policy_name == "flop_v1"
    assert "rule_path" in meta
    assert meta["rule_path"].startswith("single_raised/")
    assert any(r.get("code") == "FL_MDF_DEFEND" for r in rationale)


def test_limped_cbet_defaults_trace():
    acts = [
        LegalAction("check"),
        LegalAction("bet", min=50, max=1000),
    ]
    obs = _obs(
        acts=acts,
        to_call=0,
        pot_type="limped",
        role="na",
        board_texture="semi",
        spr_bucket="na",
    )

    suggested, rationale, policy_name, meta = policy_flop_v1(obs, PolicyConfig())

    # 按当前规则：limped + semi 默认是 check；但应包含 rule_path（用于教学追踪）
    assert suggested["action"] in {"check", "bet"}
    assert "rule_path" in meta
    assert any(x in meta["rule_path"] for x in ["limped/role:na", "limped/role/na"])


def test_threebet_semibluff_raise_size():
    acts = [
        LegalAction("call", to_call=120),
        LegalAction("raise", min=400, max=1200),
    ]
    obs = _obs(
        acts=acts,
        to_call=120,
        pot_now=480,
        pot_type="threebet",
        hand_class=HC_STRONG_DRAW,
        hand_strength=HandStrength("flop", "flop_strong_draw", HC_STRONG_DRAW),
        facing_size_tag="third",
        spr_bucket="le3",
    )

    suggested, rationale, policy_name, meta = policy_flop_v1(obs, PolicyConfig())

    assert suggested["action"] == "raise"
    assert meta["size_tag"] == "half"
    assert any(r.get("code") == "FL_RAISE_SEMI_BLUFF" for r in rationale)
