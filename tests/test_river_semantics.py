from __future__ import annotations

from poker_core.domain.actions import LegalAction
from poker_core.suggest.river_semantics import analyze_river_context
from poker_core.suggest.types import Observation


def _mk_obs(hole: list[str], board: list[str]) -> Observation:
    return Observation(
        hand_id="h",
        actor=0,
        street="river",
        bb=50,
        pot=100,
        to_call=0,
        acts=[LegalAction("check")],
        tags=[],
        hand_class="",
        hole=tuple(hole),
        board=tuple(board),
    )


def test_board_made_nuts_remains_strong_value():
    obs = _mk_obs(["9c", "9d"], ["Ah", "Kh", "Qh", "Jh", "Th"])
    ctx = analyze_river_context(obs)
    assert ctx["tier"] == "strong_value"
    assert ctx["combo"]["hero_use"] == 0


def test_board_made_strong_but_vulnerable_is_weak_showdown():
    obs = _mk_obs(["9c", "9d"], ["2h", "3h", "4h", "5h", "9h"])
    ctx = analyze_river_context(obs)
    assert ctx["tier"] == "weak_showdown"
    assert ctx["combo"]["hero_use"] == 0


def test_hero_contribution_keeps_strong_value():
    obs = _mk_obs(["Th", "9h"], ["Ah", "Kh", "Qh", "Jh", "2d"])
    ctx = analyze_river_context(obs)
    assert ctx["tier"] == "strong_value"
    assert ctx["combo"]["hero_use"] >= 1


def test_board_quads_of_aces_are_nuts_even_with_king_kicker():
    obs = _mk_obs(["2c", "3d"], ["Ah", "Ad", "Ac", "As", "Kh"])
    ctx = analyze_river_context(obs)
    assert ctx["combo"]["hero_use"] == 0
    assert ctx["combo"]["category"] == "four_kind"
    assert ctx["tier"] == "strong_value"
