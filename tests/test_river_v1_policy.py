from __future__ import annotations

from poker_core.domain.actions import LegalAction
from poker_core.suggest.service import build_suggestion


class _P:
    def __init__(self, stack=10000, invested=0, hole=None):
        self.stack = stack
        self.invested_street = invested
        self.hole = hole or ["Ah", "Kh"]


class _GS:
    def __init__(
        self,
        *,
        hand_id="h_r",
        street="river",
        button=0,
        to_act=0,
        bb=50,
        pot=400,
        players=None,
        board=None,
        events=None,
        last_bet=0,
    ):
        self.hand_id = hand_id
        self.session_id = "s_r"
        self.street = street
        self.button = button
        self.to_act = to_act
        self.bb = bb
        self.pot = pot
        self.players = players or (_P(), _P())
        self.board = board or ["Ah", "7c", "2d", "Td", "2c"]
        self.events = events or [
            {"t": "raise", "who": 0, "to": 150},
            {"t": "call", "who": 1, "amount": 150},
            {"t": "board", "street": "flop"},
            {"t": "bet", "who": 0, "amount": 100},
            {"t": "fold", "who": 1},
            {"t": "board", "street": "turn"},
            {"t": "board", "street": "river"},
        ]
        self.last_bet = last_bet


def _set_env(monkeypatch):
    monkeypatch.setenv("SUGGEST_POLICY_VERSION", "v1")
    monkeypatch.setenv("SUGGEST_V1_ROLLOUT_PCT", "0")


def _patch_acts(monkeypatch, acts):
    import poker_core.suggest.service as svc

    def _fake(_):
        return acts

    monkeypatch.setattr(svc, "legal_actions_struct", _fake)


def test_river_nobet_returns_action_and_meta(monkeypatch):
    _set_env(monkeypatch)
    acts = [LegalAction("bet", min=50, max=1000), LegalAction("check")]
    _patch_acts(monkeypatch, acts)
    gs = _GS(to_act=0)
    r = build_suggestion(gs, 0)
    assert r["policy"] == "river_v1"
    assert r["suggested"]["action"] in {"bet", "raise", "check"}
    if r["suggested"]["action"] in {"bet", "raise"}:
        assert (r.get("meta") or {}).get("size_tag") in {"third", "half", "two_third", "pot"}


def test_river_facing_half_shows_mdf(monkeypatch):
    _set_env(monkeypatch)
    acts = [LegalAction("call", to_call=100), LegalAction("fold")]
    _patch_acts(monkeypatch, acts)
    gs = _GS(to_act=1, last_bet=100)
    r = build_suggestion(gs, 1)
    assert r["policy"] == "river_v1"
    assert r["suggested"]["action"] in {"call", "fold", "raise"}
    assert 0.0 <= (r.get("meta") or {}).get("mdf", 1) <= 1.0
