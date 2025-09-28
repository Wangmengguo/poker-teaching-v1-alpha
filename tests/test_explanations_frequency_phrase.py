from __future__ import annotations

from dataclasses import dataclass

import pytest
from poker_core.domain.actions import LegalAction
from poker_core.suggest.service import POLICY_REGISTRY_V1
from poker_core.suggest.service import build_suggestion


@dataclass
class _Player:
    stack: int = 10000
    invested: int = 0
    hole: list[str] | None = None

    def __post_init__(self) -> None:
        if self.hole is None:
            self.hole = ["Ah", "Kh"]


def _cards_for_street(street: str) -> list[str]:
    board = ["Ah", "7c", "2d", "Td", "2c"]
    if street == "flop":
        return board[:3]
    if street == "turn":
        return board[:4]
    if street == "river":
        return board[:5]
    return []


@dataclass
class _GS:
    hand_id: str = "freq_phrase_hand"
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
def _force_v1(monkeypatch):
    monkeypatch.setenv("SUGGEST_POLICY_VERSION", "v1")
    monkeypatch.setenv("SUGGEST_V1_ROLLOUT_PCT", "0")


@pytest.fixture
def _patch_observation(monkeypatch):
    def _annotate(gs, actor):
        return {"info": {"tags": ["pair"], "hand_class": "value_two_pair_plus"}}

    monkeypatch.setattr(
        "poker_core.suggest.service.annotate_player_hand_from_gs",
        _annotate,
    )
    monkeypatch.setattr(
        "poker_core.suggest.observations.infer_flop_hand_class_from_gs",
        lambda gs, actor: "value_two_pair_plus",
    )
    monkeypatch.setattr(
        "poker_core.suggest.observations._spr_bucket",
        lambda spr: "ge6",
    )
    monkeypatch.setattr(
        "poker_core.suggest.observations.derive_facing_size_tag",
        lambda *args, **kwargs: "half",
    )


def _run_with_frequency(monkeypatch, freq) -> list[str]:
    acts = [LegalAction("call", to_call=100), LegalAction("fold")]
    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", lambda gs: acts)

    def _stub_policy(obs, cfg):
        meta = {
            "mdf": 0.66,
            "pot_odds": 0.34,
            "size_tag": "half",
            "frequency": freq,
        }
        rationale = []
        return {"action": "call"}, rationale, "flop_v1", meta

    monkeypatch.setitem(POLICY_REGISTRY_V1, "flop", _stub_policy)

    gs = _GS(street="flop", to_act=1, last_bet=100)
    result = build_suggestion(gs, actor=1)
    return result.get("explanations") or []


@pytest.mark.usefixtures("_patch_observation")
def test_frequency_phrase_rendered(monkeypatch):
    explanations = _run_with_frequency(monkeypatch, 0.75)
    assert any("混合策略抽样" in line for line in explanations)
    assert any("~75%" in line for line in explanations)


@pytest.mark.usefixtures("_patch_observation")
@pytest.mark.parametrize(
    "freq, expected",
    [
        (0.0, "~0%"),
        (1.0, "~100%"),
        (0.003, "~<1%"),
        ("80%", "~80%"),
    ],
)
def test_frequency_phrase_handles_boundaries(monkeypatch, freq, expected):
    explanations = _run_with_frequency(monkeypatch, freq)
    combined = " ".join(explanations)
    assert expected in combined


@pytest.mark.usefixtures("_patch_observation")
def test_frequency_phrase_skips_invalid_input(monkeypatch):
    explanations = _run_with_frequency(monkeypatch, "n/a")
    combined = " ".join(explanations)
    assert "混合策略抽样" not in combined


@pytest.mark.usefixtures("_patch_observation")
def test_river_blocker_explanation(monkeypatch):
    acts = [LegalAction("bet", min=50, max=400), LegalAction("check")]
    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", lambda gs: acts)

    river_meta = {
        "size_tag": "third",
        "frequency": None,
        "river_value_tier": "strong_value",
        "river_blockers": ["nut_flush_blocker"],
        "plan": "拥有坚果同花阻断，转为过牌诱导",
        "facing_size_tag": "na",
    }

    def _stub_policy(obs, cfg):
        return {"action": "check"}, [], "river_v1", dict(river_meta)

    monkeypatch.setitem(POLICY_REGISTRY_V1, "river", _stub_policy)

    gs = _GS(street="river", to_act=0)
    result = build_suggestion(gs, actor=0)
    explanations = result.get("explanations") or []
    combined = " ".join(explanations)
    assert "强成手" in combined
    assert "坚果同花阻断" in combined
    assert "过牌" in combined


@pytest.mark.usefixtures("_patch_observation")
def test_river_facing_decision_explanation(monkeypatch):
    acts = [LegalAction("call", to_call=300), LegalAction("fold")]
    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", lambda gs: acts)

    river_meta = {
        "size_tag": None,
        "frequency": None,
        "river_value_tier": "weak_showdown",
        "river_blockers": [],
        "plan": "弱摊牌优先免费摊牌",
        "facing_size_tag": "two_third+",
    }

    def _stub_policy(obs, cfg):
        return {"action": "fold"}, [], "river_v1", dict(river_meta)

    monkeypatch.setitem(POLICY_REGISTRY_V1, "river", _stub_policy)

    gs = _GS(street="river", to_act=1, last_bet=300)
    result = build_suggestion(gs, actor=1)
    explanations = result.get("explanations") or []
    combined = " ".join(explanations)
    assert "弱摊牌" in combined
    assert "大注" in combined or "大额" in combined
    assert "弃牌" in combined
