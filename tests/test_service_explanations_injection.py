from __future__ import annotations

import pytest
from poker_core.domain.actions import LegalAction
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


def test_service_injects_explanations(monkeypatch, patch_analysis):
    # Legal actions: allow call/check for safe suggestion
    acts = [
        LegalAction("call", to_call=100),
        LegalAction("check"),
    ]

    def _legal_actions(_):
        return acts

    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", _legal_actions)
    monkeypatch.setenv("SUGGEST_POLICY_VERSION", "v1")
    monkeypatch.setenv("SUGGEST_LOCALE", "zh")

    def _stub_policy(obs, cfg):
        # deterministic rationale + meta for rendering
        rationale = [
            {
                "code": "FL_MDF_DEFEND",
                "data": {"mdf": 0.66, "pot_odds": 0.34, "facing": "half"},
            }
        ]
        meta = {"mdf": 0.66, "pot_odds": 0.34, "size_tag": "half"}
        return {"action": "call"}, rationale, "flop_v1", meta

    monkeypatch.setitem(POLICY_REGISTRY_V1, "flop", _stub_policy)

    gs = _GS()

    result = build_suggestion(gs, actor=0)

    # Explanations should be present and contain rendered numbers
    exp = result.get("explanations")
    assert isinstance(exp, list) and exp
    txt = " ".join(exp)
    assert "MDF" in txt and "0.66" in txt
    assert "锅赔率" in txt and "0.34" in txt
