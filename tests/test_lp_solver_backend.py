import math

import pytest

from tools import lp_solver


@pytest.fixture
def toy_problem() -> tuple[dict, dict, dict, dict]:
    tree = {
        "root": "hero_root",
        "nodes": [
            {
                "id": "hero_root",
                "player": "hero",
                "actions": [
                    {"name": "bet", "next": "villain_after_bet"},
                    {"name": "check", "next": "villain_after_check"},
                ],
            },
            {
                "id": "villain_after_bet",
                "player": "villain",
                "actions": [
                    {"name": "fold", "leaf": "leaf_bet_fold"},
                    {"name": "call", "leaf": "leaf_bet_call"},
                ],
            },
            {
                "id": "villain_after_check",
                "player": "villain",
                "actions": [
                    {"name": "fold", "leaf": "leaf_check_fold"},
                    {"name": "call", "leaf": "leaf_check_call"},
                ],
            },
        ],
    }
    buckets = {"hero": ["H0"], "villain": ["V0"]}
    transitions = {
        "turn_to_river": [[1.0]],
    }
    leaf_ev = {
        "leaf_bet_fold": 0.2,
        "leaf_bet_call": -0.1,
        "leaf_check_fold": 0.0,
        "leaf_check_call": 0.05,
    }
    return tree, buckets, transitions, leaf_ev


def test_highs_solver_solves_toy_tree(toy_problem):
    tree, buckets, transitions, leaf_ev = toy_problem
    result = lp_solver.solve_lp(tree, buckets, transitions, leaf_ev, backend="highs", seed=None)

    assert result["backend"] == "highs"
    assert math.isclose(result["value"], 0.0285714286, rel_tol=1e-7)

    hero_strategy = result["strategy"]
    assert set(hero_strategy) == {"bet", "check"}
    assert math.isclose(hero_strategy["bet"], 0.1428571429, rel_tol=1e-6)
    assert math.isclose(hero_strategy["check"], 0.8571428571, rel_tol=1e-6)

    dual = result["dual_prices"]
    assert set(dual) == {"fold", "call"}
    assert math.isclose(dual["fold"], 0.4285714286, rel_tol=1e-6)
    assert math.isclose(dual["call"], 0.5714285714, rel_tol=1e-6)

    assert result["meta"]["status"] == "optimal"
    assert result["meta"]["iterations"] >= 1


def test_linprog_fallback_when_highs_missing(monkeypatch, toy_problem):
    tree, buckets, transitions, leaf_ev = toy_problem

    baseline = lp_solver.solve_lp(tree, buckets, transitions, leaf_ev, backend="linprog")

    def _raise_import():
        raise ImportError("no highs available")

    monkeypatch.setattr(lp_solver, "_import_highspy", _raise_import)

    auto = lp_solver.solve_lp(tree, buckets, transitions, leaf_ev, backend="auto")

    assert auto["backend"] == "linprog"
    for action, prob in baseline["strategy"].items():
        assert math.isclose(auto["strategy"][action], prob, rel_tol=1e-6, abs_tol=1e-9)
    assert math.isclose(auto["value"], baseline["value"], rel_tol=1e-6, abs_tol=1e-9)


def test_invalid_inputs_raise_diagnostic_error(toy_problem):
    tree, buckets, transitions, leaf_ev = toy_problem
    tree = dict(tree)
    tree["nodes"] = list(tree["nodes"])
    tree["nodes"][0] = {
        "id": "hero_root",
        "player": "hero",
        "actions": [
            {"name": "bet", "next": "villain_after_bet"},
            {"name": "check", "next": "villain_after_missing"},
        ],
    }

    with pytest.raises(lp_solver.LPSolverError) as excinfo:
        lp_solver.solve_lp(tree, buckets, transitions, leaf_ev, backend="linprog")

    message = str(excinfo.value)
    assert "villain_after_missing" in message
    assert "missing" in message.lower()
