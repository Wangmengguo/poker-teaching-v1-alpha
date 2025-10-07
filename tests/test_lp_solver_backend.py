import json
import math

import pytest

from tools import solve_lp as lp_solver


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
                "policy": {
                    "node_key": "preflop/single_raised/role:pfr/ip/texture:na/spr:mid/facing:na/bucket:0",
                    "street": "preflop",
                    "pot_type": "single_raised",
                    "role": "pfr",
                    "pos": "ip",
                    "texture": "na",
                    "spr": "mid",
                    "bucket": 0,
                    "actions": [
                        {"action": "bet", "size_tag": "2.5x"},
                        {"action": "check"},
                    ],
                },
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
        "policy_nodes": [
            {
                "node_key": "flop/single_raised/role:caller/oop/texture:dry/spr:mid/facing:na/bucket:4",
                "street": "flop",
                "pot_type": "single_raised",
                "role": "caller",
                "pos": "oop",
                "texture": "dry",
                "spr": "mid",
                "bucket": 4,
                "actions": [
                    {"action": "bet", "size_tag": "33", "weight": 0.0},
                    {"action": "check", "weight": 1.0},
                ],
            },
            {
                "node_key": "turn/single_raised/role:pfr/ip/texture:semi/spr:low/facing:na/bucket:2",
                "street": "turn",
                "pot_type": "single_raised",
                "role": "pfr",
                "pos": "ip",
                "texture": "semi",
                "spr": "low",
                "bucket": 2,
                "actions": [
                    {"action": "bet", "size_tag": "75", "weight": 0.4},
                    {"action": "check", "weight": 0.6},
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
    result = lp_solver.solve_lp(
        tree, buckets, transitions, leaf_ev, backend="highs", seed=None, small_engine="off"
    )

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

    baseline = lp_solver.solve_lp(
        tree, buckets, transitions, leaf_ev, backend="linprog", small_engine="off"
    )

    def _raise_import():
        raise ImportError("no highs available")

    monkeypatch.setattr(lp_solver, "_import_highspy", _raise_import)

    auto = lp_solver.solve_lp(
        tree, buckets, transitions, leaf_ev, backend="auto", small_engine="off"
    )

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
        lp_solver.solve_lp(
            tree, buckets, transitions, leaf_ev, backend="linprog", small_engine="off"
        )

    message = str(excinfo.value)
    assert "villain_after_missing" in message
    assert "missing" in message.lower()


def test_solver_emits_policy_nodes(tmp_path, toy_problem):
    tree, buckets, transitions, leaf_ev = toy_problem
    result = lp_solver.solve_lp(tree, buckets, transitions, leaf_ev, backend="linprog", seed=7)

    nodes = result.get("nodes")
    assert isinstance(nodes, list) and len(nodes) >= 3

    preflop = next((node for node in nodes if node["street"] == "preflop"), None)
    assert preflop is not None
    assert (
        preflop["node_key"]
        == "preflop/single_raised/role:pfr/ip/texture:na/spr:mid/facing:na/bucket:0"
    )

    hero_strategy = result["strategy"]
    actions = {arm["action"]: arm for arm in preflop["actions"]}
    assert set(actions) == set(hero_strategy)
    for name, weight in hero_strategy.items():
        assert math.isclose(actions[name]["weight"], weight, rel_tol=1e-7)

    flop = next((node for node in nodes if node["street"] == "flop"), None)
    assert flop is not None
    assert flop["actions"][0]["action"] == "bet"
    assert flop["actions"][1]["weight"] == 1.0

    meta = result.get("meta", {})
    assert meta.get("solver_backend") == result.get("backend")
    assert meta.get("tree_hash")
    assert meta.get("node_count") == len(nodes)


def test_cli_writes_solution_with_nodes(tmp_path, toy_problem):
    tree, buckets, transitions, leaf_ev = toy_problem

    tree_path = tmp_path / "tree.json"
    buckets_path = tmp_path / "buckets.json"
    transitions_path = tmp_path / "transitions.json"
    leaf_path = tmp_path / "leaf.json"
    out_path = tmp_path / "solution.json"

    tree_path.write_text(json.dumps(tree))
    buckets_path.write_text(json.dumps(buckets))
    transitions_path.write_text(json.dumps(transitions))
    leaf_path.write_text(json.dumps(leaf_ev))

    exit_code = lp_solver.main(
        [
            "--tree",
            str(tree_path),
            "--buckets",
            str(buckets_path),
            "--transitions",
            str(transitions_path),
            "--leaf_ev",
            str(leaf_path),
            "--solver",
            "linprog",
            "--out",
            str(out_path),
            "--seed",
            "11",
        ]
    )

    assert exit_code == 0
    payload = json.loads(out_path.read_text())
    assert payload["nodes"]
    assert payload["meta"]["solver_backend"] == payload["backend"]
    assert payload["meta"]["seed"] == 11
    assert payload["meta"]["tree_hash"]
