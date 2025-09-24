from __future__ import annotations

from poker_core.domain.actions import LegalAction
from poker_core.suggest.service import build_suggestion


class _P:
    def __init__(self, stack=10000, invested=0, hole=None):
        self.stack = stack
        self.invested_street = invested
        self.hole = hole or ["Ah", "Kh"]


def cards_for_street(street):
    """Return the correct number of board cards for the given street."""
    all_cards = ["Ah", "7c", "2d", "Td", "2c"]
    if street == "flop":
        return all_cards[:3]
    elif street == "turn":
        return all_cards[:4]
    elif street == "river":
        return all_cards[:5]
    else:
        return []


class _GS:
    def __init__(
        self,
        *,
        hand_id="h_x",
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
        self.session_id = "s_x"
        self.street = street
        self.button = button
        self.to_act = to_act
        self.bb = bb
        self.pot = pot
        self.players = players or (_P(), _P())
        self.board = board or cards_for_street(street)
        # Preflop raise by 0, call by 1, then go to street
        base = [
            {"t": "raise", "who": 0, "to": 150},
            {"t": "call", "who": 1, "amount": 150},
            {"t": "board", "street": "flop"},
        ]
        if street in {"turn", "river"}:
            base.append({"t": "board", "street": "turn"})
        if street == "river":
            base.append({"t": "board", "street": "river"})
        self.events = events or base
        self.last_bet = last_bet


def _set_env(monkeypatch):
    monkeypatch.setenv("SUGGEST_POLICY_VERSION", "v1")
    monkeypatch.setenv("SUGGEST_V1_ROLLOUT_PCT", "0")


def _patch_acts(monkeypatch, acts):
    import poker_core.suggest.service as svc

    def _fake(_):
        return acts

    monkeypatch.setattr(svc, "legal_actions_struct", _fake)


def _assert_rulepath_has_spr(meta: dict):
    rp = (meta or {}).get("rule_path", "")
    assert any(x in rp for x in ("/le3", "/3to6", "/ge6")), rp
    assert not any(x in rp for x in ("/low", "/mid", "/high")), rp


def test_turn_rulepath_uses_config_spr_keys(monkeypatch):
    _set_env(monkeypatch)
    acts = [LegalAction("bet", min=50, max=1000), LegalAction("check")]
    _patch_acts(monkeypatch, acts)
    gs = _GS(street="turn", to_act=0)
    r = build_suggestion(gs, 0)
    assert r["policy"] == "turn_v1"
    _assert_rulepath_has_spr(r.get("meta") or {})


def test_river_rulepath_uses_config_spr_keys(monkeypatch):
    _set_env(monkeypatch)
    acts = [LegalAction("bet", min=50, max=1000), LegalAction("check")]
    _patch_acts(monkeypatch, acts)
    gs = _GS(street="river", to_act=0)
    r = build_suggestion(gs, 0)
    assert r["policy"] == "river_v1"
    _assert_rulepath_has_spr(r.get("meta") or {})
