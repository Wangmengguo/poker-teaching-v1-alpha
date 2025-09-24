from __future__ import annotations

import pytest
from poker_core.domain.actions import LegalAction
from poker_core.suggest.decision import Decision, SizeSpec
from poker_core.suggest.service import POLICY_REGISTRY_V1, build_suggestion


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


def test_service_accepts_decision_output(monkeypatch, patch_analysis):
    acts = [
        LegalAction("bet", min=50, max=1000),
        LegalAction("check"),
    ]

    def _legal_actions(_):
        return acts

    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", _legal_actions)
    monkeypatch.setenv("SUGGEST_POLICY_VERSION", "v1")

    decision = Decision(
        action="bet",
        sizing=SizeSpec.tag("half"),
        meta={"size_tag": "half", "rule_path": "stub/trace"},
    )

    def _stub_policy(obs, cfg):
        return decision, [{"code": "TEST_DECISION"}], "flop_decision_stub", {"extra": 1}

    monkeypatch.setitem(POLICY_REGISTRY_V1, "flop", _stub_policy)

    gs = _GS(players=(_Player(), _Player()))

    result = build_suggestion(gs, actor=0)

    assert result["suggested"]["action"] == "bet"
    assert result["suggested"]["amount"] == 150  # half pot
    assert result["policy"] == "flop_decision_stub"
    assert result["meta"]["size_tag"] == "half"
    assert result["meta"]["rule_path"] == "stub/trace"
    assert any(r.get("code") == "TEST_DECISION" for r in result["rationale"])


def test_service_debug_includes_rule_path(monkeypatch, patch_analysis):
    acts = [
        LegalAction("bet", min=50, max=1000),
    ]

    def _legal_actions(_):
        return acts

    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", _legal_actions)
    monkeypatch.setenv("SUGGEST_POLICY_VERSION", "v1")
    monkeypatch.setenv("SUGGEST_DEBUG", "1")

    decision = Decision(
        action="bet",
        sizing=SizeSpec.tag("third"),
        meta={"size_tag": "third", "rule_path": "stub/debug"},
    )

    def _stub_policy(obs, cfg):
        return decision, [], "flop_decision_stub", {}

    monkeypatch.setitem(POLICY_REGISTRY_V1, "flop", _stub_policy)

    gs = _GS(players=(_Player(), _Player()))

    result = build_suggestion(gs, actor=0)

    assert result["suggested"]["amount"] == 100
    debug_meta = result.get("debug", {}).get("meta", {})
    assert debug_meta.get("rule_path") == "stub/debug"
