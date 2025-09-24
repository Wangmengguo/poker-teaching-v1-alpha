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
        hand_id="h_t",
        street="turn",
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
        self.session_id = "s_t"
        self.street = street
        self.button = button
        self.to_act = to_act
        self.bb = bb
        self.pot = pot
        self.players = players or (_P(), _P())
        self.board = board or ["Ah", "7c", "2d", "Td"]
        self.events = events or [
            {"t": "raise", "who": 0, "to": 150},
            {"t": "call", "who": 1, "amount": 150},
            {"t": "board", "street": "flop"},
            {"t": "check", "who": 1},
            {"t": "check", "who": 0},
            {"t": "board", "street": "turn"},
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


def test_turn_nobet_uses_rules_or_fallback(monkeypatch):
    _set_env(monkeypatch)
    acts = [LegalAction("bet", min=50, max=1000), LegalAction("check")]
    _patch_acts(monkeypatch, acts)
    gs = _GS(to_act=0)
    r = build_suggestion(gs, 0)
    assert r["policy"] == "turn_v1"
    assert r["suggested"]["action"] in {"bet", "raise", "check"}
    if r["suggested"]["action"] in {"bet", "raise"}:
        assert (r.get("meta") or {}).get("size_tag") in {"third", "half", "two_third", "pot"}
    assert "mdf" in (r.get("meta") or {}) and "pot_odds" in (r.get("meta") or {})


def test_turn_facing_bet_exposes_mdf(monkeypatch):
    _set_env(monkeypatch)
    # to_call=100, pot_now=300 → pot_odds=0.25 → mdf=0.75
    acts = [LegalAction("call", to_call=100), LegalAction("fold")]
    _patch_acts(monkeypatch, acts)
    gs = _GS(to_act=1, last_bet=100)
    r = build_suggestion(gs, 1)
    assert r["policy"] == "turn_v1"
    assert r["suggested"]["action"] in {"call", "fold", "raise"}
    assert 0.0 <= (r.get("meta") or {}).get("mdf", 1) <= 1.0
