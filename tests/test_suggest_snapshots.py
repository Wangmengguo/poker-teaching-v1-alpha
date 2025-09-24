from __future__ import annotations

import json
from pathlib import Path

import pytest
from poker_core.domain.actions import LegalAction
from poker_core.suggest.service import build_suggestion

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


def _load_snapshot(name: str) -> dict:
    path = SNAPSHOT_DIR / f"{name}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _store_snapshot(name: str, data: dict) -> None:
    path = SNAPSHOT_DIR / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


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
        street="preflop",
        button=0,
        to_act=0,
        bb=50,
        pot=150,
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
        self.board = board or []
        self.events = events or []
        self.last_bet = last_bet


@pytest.fixture(autouse=True)
def patch_analysis(monkeypatch):
    def _annotate(gs, actor):
        return {"info": {"tags": ["suited_broadway"], "hand_class": "value_two_pair_plus"}}

    monkeypatch.setattr(
        "poker_core.suggest.service.annotate_player_hand_from_gs",
        _annotate,
    )


@pytest.mark.parametrize(
    "name,gs_factory,acts",
    [
        (
            "preflop_sb_open",
            lambda: _GS(
                street="preflop",
                button=0,
                to_act=0,
                players=(
                    _Player(invested=25, hole=["Ah", "Qd"]),
                    _Player(invested=50),
                ),
            ),
            [
                LegalAction("check"),
                LegalAction("raise", min=100, max=400),
            ],
        ),
        (
            "preflop_bb_defend",
            lambda: _GS(
                street="preflop",
                button=0,
                to_act=1,
                players=(
                    _Player(invested=125),
                    _Player(invested=50, hole=["As", "Qs"]),
                ),
            ),
            [
                LegalAction("fold"),
                LegalAction("call", to_call=75),
                LegalAction("raise", min=250, max=600),
            ],
        ),
        (
            "flop_pfr_cbet",
            lambda: _GS(
                street="flop",
                button=0,
                to_act=0,
                pot=300,
                players=(
                    _Player(invested=150),
                    _Player(invested=150),
                ),
                board=["Ah", "7c", "2d"],
                events=[{"t": "raise", "who": 0, "to": 150}, {"t": "board", "street": "flop"}],
            ),
            [
                LegalAction("bet", min=50, max=1000),
                LegalAction("check"),
            ],
        ),
        (
            "flop_value_raise",
            lambda: _GS(
                street="flop",
                button=0,
                to_act=0,
                pot=500,
                players=(
                    _Player(invested=250),
                    _Player(invested=250),
                ),
                board=["Ah", "7c", "2d"],
                events=[
                    {"t": "raise", "who": 0, "to": 150},
                    {"t": "call", "who": 1, "amount": 150},
                    {"t": "board", "street": "flop"},
                    {"t": "bet", "who": 1, "amount": 100},
                ],
                last_bet=100,
            ),
            [
                LegalAction("call", to_call=100),
                LegalAction("raise", min=400, max=1200),
                LegalAction("fold"),
            ],
        ),
        (
            "turn_pfr_ip_nobet",
            lambda: _GS(
                street="turn",
                button=0,
                to_act=0,
                pot=300,
                players=(
                    _Player(invested=150),
                    _Player(invested=150),
                ),
                board=["Ah", "7c", "2d", "Td"],
                events=[
                    {"t": "raise", "who": 0, "to": 150},
                    {"t": "call", "who": 1, "amount": 150},
                    {"t": "board", "street": "flop"},
                    {"t": "check", "who": 1},
                    {"t": "check", "who": 0},
                    {"t": "board", "street": "turn"},
                ],
            ),
            [
                LegalAction("bet", min=50, max=1000),
                LegalAction("check"),
            ],
        ),
        (
            "turn_facing_half_call",
            lambda: _GS(
                street="turn",
                button=0,
                to_act=1,
                pot=100,
                players=(
                    _Player(invested=50),
                    _Player(invested=50),
                ),
                board=["Ah", "7c", "2d", "Td"],
                events=[
                    {"t": "raise", "who": 0, "to": 150},
                    {"t": "call", "who": 1, "amount": 150},
                    {"t": "board", "street": "flop"},
                    {"t": "board", "street": "turn"},
                    {"t": "bet", "who": 0, "amount": 100},
                ],
                last_bet=100,
            ),
            [
                LegalAction("call", to_call=100),
                LegalAction("fold"),
            ],
        ),
        (
            "turn_oop_check",
            lambda: _GS(
                street="turn",
                button=0,
                to_act=1,
                pot=300,
                players=(
                    _Player(invested=150),
                    _Player(invested=150),
                ),
                board=["Ah", "7c", "2d", "Td"],
                events=[
                    {"t": "raise", "who": 0, "to": 150},
                    {"t": "call", "who": 1, "amount": 150},
                    {"t": "board", "street": "flop"},
                    {"t": "board", "street": "turn"},
                ],
            ),
            [
                LegalAction("check"),
            ],
        ),
        (
            "river_pfr_ip_nobet",
            lambda: _GS(
                street="river",
                button=0,
                to_act=0,
                pot=300,
                players=(
                    _Player(invested=150),
                    _Player(invested=150),
                ),
                board=["Ah", "7c", "2d", "Td", "2c"],
                events=[
                    {"t": "raise", "who": 0, "to": 150},
                    {"t": "call", "who": 1, "amount": 150},
                    {"t": "board", "street": "flop"},
                    {"t": "check", "who": 1},
                    {"t": "check", "who": 0},
                    {"t": "board", "street": "turn"},
                    {"t": "board", "street": "river"},
                ],
            ),
            [
                LegalAction("bet", min=50, max=1000),
                LegalAction("check"),
            ],
        ),
        (
            "river_facing_half_call",
            lambda: _GS(
                street="river",
                button=0,
                to_act=1,
                pot=100,
                players=(
                    _Player(invested=50),
                    _Player(invested=50),
                ),
                board=["Ah", "7c", "2d", "Td", "2c"],
                events=[
                    {"t": "raise", "who": 0, "to": 150},
                    {"t": "call", "who": 1, "amount": 150},
                    {"t": "board", "street": "flop"},
                    {"t": "board", "street": "turn"},
                    {"t": "board", "street": "river"},
                    {"t": "bet", "who": 0, "amount": 100},
                ],
                last_bet=100,
            ),
            [
                LegalAction("call", to_call=100),
                LegalAction("fold"),
            ],
        ),
        (
            "river_oop_check",
            lambda: _GS(
                street="river",
                button=0,
                to_act=1,
                pot=300,
                players=(
                    _Player(invested=150),
                    _Player(invested=150),
                ),
                board=["Ah", "7c", "2d", "Td", "2c"],
                events=[
                    {"t": "raise", "who": 0, "to": 150},
                    {"t": "call", "who": 1, "amount": 150},
                    {"t": "board", "street": "flop"},
                    {"t": "board", "street": "turn"},
                    {"t": "board", "street": "river"},
                ],
            ),
            [
                LegalAction("check"),
            ],
        ),
    ],
)
def test_snapshot(name, gs_factory, acts, monkeypatch):
    def _legal_actions(_):
        return acts

    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", _legal_actions)
    monkeypatch.setenv("SUGGEST_POLICY_VERSION", "v1")

    gs = gs_factory()

    result = build_suggestion(gs, actor=gs.to_act)

    snapshot = _load_snapshot(name)

    filtered = {
        "suggested": result["suggested"],
        "policy": result["policy"],
        "meta": {
            k: v
            for k, v in (result.get("meta") or {}).items()
            if k
            in {
                "size_tag",
                "open_bb",
                "bucket",
                "reraise_to_bb",
                "fourbet_to_bb",
                "rule_path",
                "plan",
            }
        },
        "codes": [r.get("code") for r in result["rationale"]],
    }

    if not snapshot:
        _store_snapshot(name, filtered)
        pytest.skip(f"Snapshot {name} created; rerun to assert.")

    assert filtered == snapshot
