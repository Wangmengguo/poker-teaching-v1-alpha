"""Minimal coverage for conservative fallback behavior."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from poker_core.domain.actions import LegalAction
from poker_core.suggest.codes import SCodes
from poker_core.suggest.service import POLICY_REGISTRY_V1, build_suggestion


@dataclass
class _Player:
    stack: int = 10000
    invested_street: int = 0
    hole: list[str] | None = None

    def __post_init__(self) -> None:
        if self.hole is None:
            self.hole = ["Ah", "Kd"]


def _cards_for_street(street: str) -> list[str]:
    board = ["7h", "4d", "2c", "Qs", "9d"]
    if street == "flop":
        return board[:3]
    if street == "turn":
        return board[:4]
    if street == "river":
        return board[:5]
    return []


@dataclass
class _GS:
    hand_id: str = "h_fb"
    street: str = "flop"
    button: int = 0
    to_act: int = 0
    bb: int = 50
    pot: int = 300
    players: tuple[_Player, _Player] | None = None
    board: list[str] | None = None
    events: list[dict] | None = None
    last_bet: int = 0

    def __post_init__(self) -> None:
        if self.players is None:
            self.players = (_Player(), _Player())
        if self.board is None:
            self.board = _cards_for_street(self.street)
        if self.events is None:
            base = [
                {"t": "raise", "who": 0, "to": 150},
                {"t": "call", "who": 1, "amount": 150},
                {"t": "board", "street": "flop"},
            ]
            if self.street in {"turn", "river"}:
                base.append({"t": "board", "street": "turn"})
            if self.street == "river":
                base.append({"t": "board", "street": "river"})
            self.events = base


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    monkeypatch.setenv("SUGGEST_POLICY_VERSION", "v1")
    monkeypatch.setenv("SUGGEST_V1_ROLLOUT_PCT", "0")


@pytest.fixture
def patch_analysis(monkeypatch):
    def _annotate(gs, actor):
        return {"info": {"tags": ["pair"], "hand_class": "value_two_pair_plus"}}

    monkeypatch.setattr(
        "poker_core.suggest.service.annotate_player_hand_from_gs",
        _annotate,
    )

    def _infer_flop(gs, actor):
        return "value_two_pair_plus"

    monkeypatch.setattr(
        "poker_core.suggest.observations.infer_flop_hand_class_from_gs",
        _infer_flop,
    )

    monkeypatch.setattr(
        "poker_core.suggest.observations._spr_bucket",
        lambda spr: "ge6",
    )

    monkeypatch.setattr(
        "poker_core.suggest.observations.derive_facing_size_tag",
        lambda *args, **kwargs: "half",
    )


def test_missing_rule_triggers_fallback_and_code(monkeypatch, patch_analysis):
    acts = [LegalAction("check"), LegalAction("fold")]

    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", lambda gs: acts)

    def _policy_stub(obs, cfg):
        return {"action": "raise"}, [], "flop_v1", {"rule_path": "missing"}

    monkeypatch.setitem(POLICY_REGISTRY_V1, "flop", _policy_stub)

    gs = _GS(street="flop", to_act=0)
    result = build_suggestion(gs, actor=0)

    assert result["suggested"]["action"] in {"check", "fold"}
    codes = {item.get("code") for item in result.get("rationale", [])}
    assert SCodes.CFG_FALLBACK_USED.code in codes


def test_no_raise_in_fallback(monkeypatch, patch_analysis):
    acts = [
        LegalAction("raise", min=200, max=1000),
        LegalAction("call", to_call=600),
        LegalAction("fold"),
    ]

    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", lambda gs: acts)

    def _policy_stub(obs, cfg):
        raise RuntimeError("missing policy node")

    monkeypatch.setitem(POLICY_REGISTRY_V1, "flop", _policy_stub)

    gs = _GS(street="flop", to_act=0, pot=200, last_bet=600)
    result = build_suggestion(gs, actor=0)

    assert result["suggested"]["action"] in {"fold", "check", "call"}
    assert result["suggested"]["action"] != "raise"
    codes = {item.get("code") for item in result.get("rationale", [])}
    assert SCodes.CFG_FALLBACK_USED.code in codes


def test_preflop_limp_threshold(monkeypatch, patch_analysis):
    acts = [
        LegalAction("call", to_call=50),
        LegalAction("check"),
        LegalAction("fold"),
    ]

    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", lambda gs: acts)

    gs = _GS(street="preflop", to_act=0, pot=75)
    result = build_suggestion(gs, actor=0)

    assert result["suggested"]["action"] == "call"
    codes = {item.get("code") for item in result.get("rationale", [])}
    assert SCodes.PF_LIMP_COMPLETE_BLIND.code in codes
