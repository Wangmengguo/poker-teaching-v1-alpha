import pytest
from poker_core.domain.actions import LegalAction
from poker_core.suggest.policy import policy_postflop_v0_3, policy_preflop_v0, policy_preflop_v1
from poker_core.suggest.types import Observation, PolicyConfig


def _obs(**kw):
    # 构造最小 Observation（acts 必填）
    defaults = dict(
        hand_id="h_test",
        actor=0,
        street="preflop",
        bb=50,
        pot=0,
        to_call=0,
        acts=[],
        tags=[],
        hand_class="weak",
    )
    defaults.update(kw)
    return Observation(**defaults)  # type: ignore


def test_preflop_open_uses_bb_target_and_respects_bounds():
    acts = [
        LegalAction(action="bet", min=100, max=300),
        LegalAction(action="check"),
    ]
    obs = _obs(acts=acts, tags=["pair"], hand_class="pair")
    suggested, rationale, policy = policy_preflop_v0(obs, PolicyConfig(open_size_bb=2.5))
    assert policy == "preflop_v0"
    assert suggested["action"] == "bet"
    # 2.5bb = 125，在 [100,300] 内 → 125
    assert suggested["amount"] == 125
    assert any(r["code"] in {"PF_OPEN_BET", "PF_OPEN_RAISE"} for r in rationale)


def test_preflop_facing_bet_calls_within_threshold():
    acts = [
        LegalAction(action="call", to_call=100),
        LegalAction(action="fold"),
    ]
    obs = _obs(acts=acts, to_call=100, tags=["broadway_offsuit"], hand_class="broadway_offsuit")
    suggested, rationale, policy = policy_preflop_v0(obs, PolicyConfig(call_threshold_bb=3))
    assert policy == "preflop_v0"
    assert suggested["action"] == "call"
    assert any(r["code"] == "PF_CALL" for r in rationale)


def test_postflop_flop_min_probe_bet():
    acts = [
        LegalAction(action="bet", min=50, max=500),
        LegalAction(action="check"),
    ]
    obs = _obs(street="flop", acts=acts)
    suggested, rationale, policy = policy_postflop_v0_3(obs, PolicyConfig())
    assert policy == "postflop_v0_3"
    assert suggested["action"] == "bet"
    assert suggested["amount"] == 50  # 最小下注
    assert any(r["code"] == "PL_PROBE_BET" for r in rationale)


@pytest.mark.parametrize(
    "tags,hand_class,expect_call",
    [
        ([], "weak", True),  # 0.318 <= 0.33 → 跟注
        (["pair"], "pair", True),  # 范围内阈值更宽 0.40 → 跟注
    ],
)
def test_postflop_call_by_pot_odds(tags, hand_class, expect_call):
    acts = [
        LegalAction(action="call", to_call=140),
        LegalAction(action="fold"),
    ]
    # pot=300, to_call=140 → pot_odds = 140 / (300+140) ≈ 0.318
    obs = _obs(street="turn", acts=acts, pot=300, to_call=140, tags=tags, hand_class=hand_class)
    suggested, rationale, policy = policy_postflop_v0_3(obs, PolicyConfig())
    assert policy == "postflop_v0_3"
    assert suggested["action"] == ("call" if expect_call else "fold")


def test_preflop_v1_sb_first_in_limp_completion():
    """测试SB首入补盲逻辑，当前有bug：条件矛盾导致limp不可达"""
    acts = [
        LegalAction(action="call", to_call=50),  # 需要补50到BB
        LegalAction(action="raise", min=100, max=400),
    ]
    obs = _obs(
        acts=acts,
        to_call=50,  # SB需要补50到BB
        first_to_act=True,  # SB首入
        tags=["suited_broadway"],
        hand_class="AKs",
    )

    # 修复后：is_sb_first_in不再要求to_call==0，limp逻辑应该能触发
    suggested, rationale, policy, meta = policy_preflop_v1(obs, PolicyConfig())

    # 期望：应该limp补盲
    assert suggested["action"] == "call"
    assert any(r["code"] == "PF_LIMP_COMPLETE_BLIND" for r in rationale)


def test_preflop_v1_sb_first_in_check_when_no_blind_to_complete():
    """测试SB首入但无需补盲时应该check"""
    acts = [
        LegalAction(action="check"),
        LegalAction(action="raise", min=100, max=400),
    ]
    obs = _obs(
        acts=acts,
        to_call=0,  # 无需补盲
        first_to_act=True,  # SB首入
        tags=["suited_broadway"],
        hand_class="AKs",
    )

    suggested, rationale, policy, meta = policy_preflop_v1(obs, PolicyConfig())

    assert suggested["action"] == "check"
    assert "PF_LIMP_COMPLETE_BLIND" not in [r["code"] for r in rationale]  # 不应该有limp rationale
