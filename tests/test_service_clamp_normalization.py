from __future__ import annotations

import pytest
from poker_core.domain.actions import LegalAction
from poker_core.suggest.decision import Decision, SizeSpec
from poker_core.suggest.service import POLICY_REGISTRY_V0, POLICY_REGISTRY_V1, build_suggestion


class _Player:
    def __init__(self, *, stack=5000, invested=0, hole=None):
        self.stack = stack
        self.invested_street = invested
        self.hole = hole or ["Ah", "Kh"]


class _GS:
    def __init__(
        self,
        *,
        hand_id="h1",
        street="flop",
        button=0,
        to_act=0,
        bb=50,
        pot=300,
        players=None,
        board=None,
        events=None,
        last_bet=0,
    ):
        self.hand_id = hand_id
        self.session_id = "s1"
        self.street = street
        self.button = button
        self.to_act = to_act
        self.bb = bb
        self.pot = pot
        self.players = players or (_Player(), _Player())
        self.board = board or ["Ah", "7c", "2d"]
        self.events = events or [
            {"t": "raise", "who": 0, "to": 150},
            {"t": "board", "street": "flop"},
        ]
        self.last_bet = last_bet


@pytest.fixture
def patch_analysis(monkeypatch):
    def _annotate(gs, actor):
        return {"info": {"tags": ["suited_broadway"], "hand_class": "value_two_pair_plus"}}

    monkeypatch.setattr(
        "poker_core.suggest.service.annotate_player_hand_from_gs",
        _annotate,
    )


def test_min_reopen_lift_not_duplicated(monkeypatch, patch_analysis):
    acts = [
        LegalAction("raise", min=450, max=900),
    ]

    def _legal_actions(_):
        return acts

    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", _legal_actions)
    monkeypatch.setenv("SUGGEST_POLICY_VERSION", "v1")

    decision = Decision(
        action="raise",
        sizing=SizeSpec.bb(6),
        meta={},
    )

    def _stub_policy(obs, cfg):
        return decision, [{"code": "PRE_DECISION"}], "flop_stub", {}

    monkeypatch.setitem(POLICY_REGISTRY_V1, "flop", _stub_policy)

    gs = _GS(last_bet=100)

    result = build_suggestion(gs, actor=0)

    codes = [r.get("code") for r in result["rationale"]]
    assert codes.count("FL_MIN_REOPEN_ADJUSTED") == 1
    assert codes[0] == "PRE_DECISION"


def test_warn_clamped_only_when_needed(monkeypatch, patch_analysis):
    acts = [
        LegalAction("raise", min=200, max=220),
    ]

    def _legal_actions(_):
        return acts

    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", _legal_actions)
    monkeypatch.setenv("SUGGEST_POLICY_VERSION", "v1")

    decision = Decision(
        action="raise",
        sizing=SizeSpec.amount(1000),
        meta={},
    )

    def _stub_policy(obs, cfg):
        return decision, [], "flop_stub", {}

    monkeypatch.setitem(POLICY_REGISTRY_V1, "flop", _stub_policy)

    gs = _GS()

    result = build_suggestion(gs, actor=0)

    codes = [r.get("code") for r in result["rationale"]]
    assert codes.count("W_CLAMPED") == 1


def test_legacy_min_reopen_rationale_added(monkeypatch, patch_analysis):
    acts = [
        LegalAction("raise", min=400, max=900),
    ]

    def _legal_actions(_):
        return acts

    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", _legal_actions)
    monkeypatch.setenv("SUGGEST_POLICY_VERSION", "v0")

    def _legacy_policy(obs, cfg):
        return ({"action": "raise", "amount": 300}, [{"code": "LEGACY_PATH"}], "postflop_v0_3", {})

    monkeypatch.setattr(
        "poker_core.suggest.service.policy_postflop_v0_3",
        _legacy_policy,
    )
    monkeypatch.setitem(POLICY_REGISTRY_V0, "flop", _legacy_policy)

    gs = _GS(street="flop", last_bet=200)

    result = build_suggestion(gs, actor=0)

    assert result["suggested"]["amount"] == 400

    codes = [r.get("code") for r in result["rationale"]]
    assert "LEGACY_PATH" in codes
    assert codes.count("FL_MIN_REOPEN_ADJUSTED") == 1
