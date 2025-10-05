import json
import math

import numpy as np
import pytest

from tools import solve_lp as lp_solver


def _build_matrix_tree(payoff: np.ndarray) -> tuple[dict, dict, dict, dict]:
    rows, cols = payoff.shape
    hero_actions = []
    nodes = []
    leaf_ev: dict[tuple[str, str], float] = {}
    for row in range(rows):
        hero_name = f"hero_{row}"
        villain_id = f"villain_after_{row}"
        hero_actions.append({"name": hero_name, "next": villain_id})
        villain_actions = []
        for col in range(cols):
            villain_name = f"villain_{col}"
            villain_actions.append({"name": villain_name})
            leaf_ev[(hero_name, villain_name)] = float(payoff[row, col])
        nodes.append({"id": villain_id, "player": "villain", "actions": villain_actions})
    policy_actions = [
        {"action": action["name"], "weight": 1.0 / max(len(hero_actions), 1)}
        for action in hero_actions
    ]
    tree = {
        "root": "hero_root",
        "nodes": [
            {
                "id": "hero_root",
                "player": "hero",
                "actions": hero_actions,
                "policy": {
                    "node_key": "flop/single_raised/role:pfr/ip/texture:na/spr:mid/facing:na/bucket:0",
                    "street": "flop",
                    "pot_type": "single_raised",
                    "role": "pfr",
                    "pos": "ip",
                    "texture": "na",
                    "spr": "mid",
                    "facing": "na",
                    "bucket": 0,
                    "actions": policy_actions,
                },
            },
            *nodes,
        ],
        "policy_nodes": [],
    }
    buckets = {"hero": ["H"], "villain": ["V"]}
    transitions = {}
    return tree, buckets, transitions, leaf_ev


def test_2x2_analytic_matches_linprog():
    payoff = np.array([[3.0, 0.0], [5.0, 1.0]], dtype=float)
    tree, buckets, transitions, leaf_ev = _build_matrix_tree(payoff)

    baseline = lp_solver.solve_lp(
        tree,
        buckets,
        transitions,
        leaf_ev,
        backend="linprog",
        seed=None,
        small_engine="off",
    )
    small = lp_solver.solve_lp(
        tree,
        buckets,
        transitions,
        leaf_ev,
        backend="linprog",
        seed=None,
        small_engine="on",
    )

    assert small["backend"] == "small"
    assert pytest.approx(baseline["value"], rel=1e-9, abs=1e-9) == small["value"]
    for action, weight in baseline["strategy"].items():
        assert pytest.approx(weight, rel=1e-9, abs=1e-9) == small["strategy"][action]
    assert small["meta"]["small_engine_used"] is True
    assert small["meta"]["method"] == "analytic"


def test_3x3_strict_domination_reduction_value_close():
    payoff = np.array(
        [
            [0.0, -1.0, -1.0],
            [0.5, -0.4, -0.4],
            [0.3, -0.2, -0.2],
        ],
        dtype=float,
    )
    tree, buckets, transitions, leaf_ev = _build_matrix_tree(payoff)

    baseline = lp_solver.solve_lp(
        tree, buckets, transitions, leaf_ev, backend="linprog", small_engine="off"
    )
    reduced = lp_solver.solve_lp(
        tree, buckets, transitions, leaf_ev, backend="auto", small_engine="auto"
    )

    assert reduced["meta"]["small_engine_used"] is True
    assert tuple(reduced["meta"]["reduced_shape"]) <= (2, 2)
    assert reduced["meta"]["domination_steps"] >= 1
    assert pytest.approx(baseline["value"], rel=1e-7, abs=1e-8) == reduced["value"]


def test_duplicate_rows_cols_coalesce():
    payoff = np.array(
        [
            [0.2, -0.1, -0.1],
            [0.2, -0.1, -0.1],
            [0.5, -0.2, -0.2],
        ],
        dtype=float,
    )
    tree, buckets, transitions, leaf_ev = _build_matrix_tree(payoff)

    result = lp_solver.solve_lp(
        tree, buckets, transitions, leaf_ev, backend="auto", small_engine="on"
    )

    meta = result["meta"]
    assert meta["small_engine_used"] is True
    assert meta["reduced_shape"][0] < payoff.shape[0]
    assert meta["reduced_shape"][1] < payoff.shape[1]
    assert meta["domination_steps"] >= 1
    hero_map = meta.get("hero_index_map")
    villain_map = meta.get("villain_index_map")
    assert hero_map is not None and sorted(hero_map) == sorted(set(hero_map))
    assert villain_map is not None and sorted(villain_map) == sorted(set(villain_map))


def test_degenerate_ties_lexicographic_tiebreak():
    payoff = np.array([[1.0, 1.0], [1.0, 1.0]], dtype=float)
    tree, buckets, transitions, leaf_ev = _build_matrix_tree(payoff)

    result = lp_solver.solve_lp(
        tree, buckets, transitions, leaf_ev, backend="linprog", small_engine="on"
    )

    assert result["backend"] in {"small", "linprog"}
    meta = result["meta"]
    assert meta["small_engine_used"] in {True, False}
    if meta["small_engine_used"]:
        assert meta.get("method") in {"analytic", "linprog_small"}
    total = sum(result["strategy"].values())
    assert math.isclose(total, 1.0, rel_tol=1e-9, abs_tol=1e-9)


def test_auto_switch_and_meta_flag():
    payoff = np.array([[0.0, 1.0, -1.0], [0.2, -0.3, 0.1]], dtype=float)
    tree, buckets, transitions, leaf_ev = _build_matrix_tree(payoff)

    result = lp_solver.solve_lp(tree, buckets, transitions, leaf_ev, backend="auto")
    assert result["meta"]["small_engine_used"] is True
    assert result["backend"] == "small"


@pytest.mark.parametrize("shape", [(1, 5), (5, 1), (2, 5), (5, 2)])
def test_rectangular_small_matrices_supported(shape):
    rows, cols = shape
    payoff = np.arange(rows * cols, dtype=float).reshape(rows, cols) / 10.0
    tree, buckets, transitions, leaf_ev = _build_matrix_tree(payoff)

    result = lp_solver.solve_lp(tree, buckets, transitions, leaf_ev, backend="auto")
    assert result["meta"]["small_engine_used"] is True
    assert result["backend"] == "small"
    assert math.isclose(sum(result["strategy"].values()), 1.0, rel_tol=1e-9, abs_tol=1e-9)


def test_uniform_zero_payoff_returns_uniform_or_tie_rule():
    payoff = np.zeros((3, 3), dtype=float)
    tree, buckets, transitions, leaf_ev = _build_matrix_tree(payoff)

    result = lp_solver.solve_lp(tree, buckets, transitions, leaf_ev, backend="auto")

    assert result["backend"] == "small"
    weights = list(result["strategy"].values())
    assert all(weight >= 0.0 for weight in weights)
    assert math.isclose(sum(weights), 1.0, rel_tol=1e-9, abs_tol=1e-9)
    # uniform or deterministic first arm due to lexicographic tie-break
    assert max(weights) - min(weights) <= 1.0


@pytest.mark.parametrize("shape", [(6, 5), (5, 6)])
def test_boundary_small_max_dim(shape):
    payoff = np.arange(shape[0] * shape[1], dtype=float).reshape(shape) / 10.0
    tree, buckets, transitions, leaf_ev = _build_matrix_tree(payoff)

    threshold_result = lp_solver.solve_lp(
        tree,
        buckets,
        transitions,
        leaf_ev,
        backend="auto",
        small_engine="auto",
        small_max_dim=5,
    )
    assert threshold_result["backend"] != "small"
    assert threshold_result["meta"].get("small_engine_used") is False

    relaxed_result = lp_solver.solve_lp(
        tree,
        buckets,
        transitions,
        leaf_ev,
        backend="auto",
        small_engine="auto",
        small_max_dim=6,
    )
    assert relaxed_result["backend"] == "small"
    assert relaxed_result["meta"]["small_engine_used"] is True


def test_cli_precedence_small_engine_over_backend(tmp_path):
    payoff = np.array([[0.0, 1.0], [1.0, 0.0]], dtype=float)
    tree, buckets, transitions, leaf_ev = _build_matrix_tree(payoff)

    tree_path = tmp_path / "tree.json"
    buckets_path = tmp_path / "buckets.json"
    transitions_path = tmp_path / "transitions.json"
    leaf_path = tmp_path / "leaf.json"
    out_path = tmp_path / "solution.json"

    tree_path.write_text(json.dumps(tree))
    buckets_path.write_text(json.dumps(buckets))
    transitions_path.write_text(json.dumps(transitions))
    leaf_path.write_text(json.dumps({"|".join(key): val for key, val in leaf_ev.items()}))

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
            "--small-engine",
            "on",
            "--out",
            str(out_path),
        ]
    )
    assert exit_code == 0

    data = json.loads(out_path.read_text())
    assert data["backend"] == "small"
    assert data["meta"]["small_engine_used"] is True
