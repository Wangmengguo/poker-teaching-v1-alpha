"""Linear program solver wrapper with HiGHS/linprog dual backend support.

The module exposes a :func:`solve_lp` helper that operates on in-memory tree
artifacts and a small command-line interface used by automation scripts.  The
CLI focuses on robustness for long-running cloud jobs by validating inputs,
supporting bucket/transition directory layouts, and providing progress
metadata in the emitted JSON payload.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import random
import time
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
from scipy.optimize import linprog

from .numerics import EPS as NUM_EPS
from .numerics import EPS_DENOM

__all__ = ["solve_lp", "LPSolverError", "main", "_import_highspy"]


class LPSolverError(RuntimeError):
    """Raised when LP construction or backend solving fails."""


@dataclass(slots=True)
class _MatrixGame:
    hero_actions: list[str]
    villain_actions: list[str]
    payoff: np.ndarray
    hero_metadata: Mapping[str, Any]


class _BackendUnavailable(Exception):
    """Internal sentinel when a backend cannot be used."""


def _import_highspy() -> Any:
    """Return the HiGHS python module if available."""

    return importlib.import_module("highspy")


def _ensure_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LPSolverError(f"{label} must be a mapping, got {type(value)!r}")
    return value


def _ensure_sequence(value: Any, label: str) -> Sequence[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise LPSolverError(f"{label} must be a sequence of mappings")
    return value  # type: ignore[return-value]


def _lookup_leaf_value(
    leaf_ev: Mapping[Any, Any],
    *,
    leaf_id: Any,
    hero_action: str,
    villain_action: str,
) -> float:
    # First try to find the value in leaf_ev
    if leaf_id is not None and leaf_id in leaf_ev:
        value = leaf_ev[leaf_id]
    else:
        key = (hero_action, villain_action)
        if key in leaf_ev:
            value = leaf_ev[key]
        else:
            # Handle terminal nodes with fixed payoffs
            if isinstance(leaf_id, str):
                if leaf_id == "terminal_fold_pre":
                    return -50.0  # Hero folds preflop, loses SB
                elif leaf_id == "terminal_win_pre":
                    return 50.0  # Hero wins preflop, wins SB
                elif leaf_id == "terminal_fold_post":
                    return -100.0  # Hero folds postflop, loses current pot
                elif leaf_id == "terminal_showdown":
                    return 0.0  # Showdown - use neutral EV for now
                elif leaf_id == "terminal_allin":
                    return 0.0  # All-in - use neutral EV for now

            raise LPSolverError(
                f"Missing payoff for leaf {leaf_id!r} (hero={hero_action}, villain={villain_action})"
            )
    try:
        payoff = float(value)
    except Exception as exc:  # pragma: no cover - defensive
        raise LPSolverError(f"Leaf payoff for {leaf_id!r} is not numeric: {value!r}") from exc
    if not math.isfinite(payoff) or payoff < -1e6 or payoff > 1e6:
        raise LPSolverError(f"Leaf payoff for {leaf_id!r} is not finite: {payoff!r}")
    return payoff


def _build_matrix_game(tree: Mapping[str, Any], leaf_ev: Mapping[Any, Any]) -> _MatrixGame:
    tree_map = _ensure_mapping(tree, "tree")
    leaf_map = _ensure_mapping(leaf_ev, "leaf_ev")

    nodes = _ensure_sequence(tree_map.get("nodes"), "tree['nodes']")
    if not nodes:
        raise LPSolverError("tree must define at least one node")

    node_map: dict[str, Mapping[str, Any]] = {}
    for raw in nodes:
        raw_map = _ensure_mapping(raw, "node")
        # Accept both "id" (preferred) and legacy "node_id" from build_tree artifact
        node_id = raw_map.get("id")
        if node_id is None:
            node_id = raw_map.get("node_id")
        if not isinstance(node_id, str):
            raise LPSolverError("Each node must include string id")
        if node_id in node_map:
            raise LPSolverError(f"Duplicate node id detected: {node_id}")
        node_map[node_id] = raw_map

    root_id = tree_map.get("root")
    if root_id is None:
        # Fallback to the first node's id, supporting both schemas
        first = _ensure_mapping(nodes[0], "node")
        root_id = first.get("id") or first.get("node_id")
    if not isinstance(root_id, str):
        raise LPSolverError("tree must define root node id")
    if root_id not in node_map:
        raise LPSolverError(f"root node '{root_id}' missing from nodes list")

    root = node_map[root_id]
    if (root.get("player") or "hero").lower() != "hero":
        raise LPSolverError("root node must belong to hero player")

    hero_actions_raw = _ensure_sequence(root.get("actions"), "hero actions")
    hero_actions: list[str] = []
    villain_actions: list[str] | None = None
    rows: list[list[float]] = []

    for hero_action in hero_actions_raw:
        hero_map = _ensure_mapping(hero_action, "hero action")
        action_name = hero_map.get("name")
        if not isinstance(action_name, str):
            raise LPSolverError("Hero action missing name")
        next_id = hero_map.get("next")
        if not isinstance(next_id, str):
            raise LPSolverError(f"Hero action '{action_name}' missing next villain node")
        if next_id not in node_map:
            raise LPSolverError(f"Hero action '{action_name}' references unknown node '{next_id}'")
        villain_node = node_map[next_id]

        # Check if this is a terminal node (no actions needed)
        street = villain_node.get("street", "")
        if street == "terminal":
            # Terminal nodes have no actions - lookup payoff directly
            villain_raw = []
            payoff = _lookup_leaf_value(
                leaf_map,
                leaf_id=next_id,  # Use terminal node ID as leaf ID
                hero_action=action_name,
                villain_action="terminal",
            )
            row = [payoff]
            current_villain_names = ["terminal"]
        else:
            villain_raw = _ensure_sequence(
                villain_node.get("actions"), f"villain actions for {next_id}"
            )
            row: list[float] = []
            current_villain_names: list[str] = []
            for villain_action in villain_raw:
                villain_map = _ensure_mapping(villain_action, "villain action")
                villain_name = villain_map.get("name")
                if not isinstance(villain_name, str):
                    raise LPSolverError(f"Villain action missing name in node {next_id}")
                if "leaf" in villain_map:
                    leaf_id = villain_map["leaf"]
                elif "terminal" in villain_map:
                    leaf_id = villain_map["terminal"]
                else:
                    leaf_id = None
                payoff = _lookup_leaf_value(
                    leaf_map,
                    leaf_id=leaf_id,
                    hero_action=action_name,
                    villain_action=villain_name,
                )
                row.append(payoff)
                current_villain_names.append(villain_name)
            if not row:
                raise LPSolverError(f"Villain node '{next_id}' must include actions")
        if villain_actions is None:
            villain_actions = current_villain_names
        else:
            if current_villain_names != villain_actions:
                raise LPSolverError(
                    "Villain action order mismatch across hero branches; ensure symmetric action sets"
                )
        rows.append(row)
        hero_actions.append(action_name)

    if not hero_actions:
        raise LPSolverError("Hero node requires at least one action")
    if villain_actions is None:
        raise LPSolverError("Villain responses not detected from tree")

    matrix = np.array(rows, dtype=np.float64)
    if matrix.shape != (len(hero_actions), len(villain_actions)):
        raise LPSolverError("Payoff matrix shape does not match actions")
    if not np.all(np.isfinite(matrix)):
        raise LPSolverError("Payoff matrix contains non-finite values")

    return _MatrixGame(
        hero_actions=hero_actions,
        villain_actions=villain_actions,
        payoff=matrix,
        hero_metadata=root,
    )


def _canonicalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonicalize(val)
            for key, val in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_canonicalize(item) for item in value]
    return value


def _compute_tree_hash(tree: Mapping[str, Any]) -> str:
    canonical = json.dumps(_canonicalize(tree), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _extract_component(source: Mapping[str, Any], key: str, default: Any) -> Any:
    if key in source:
        return source[key]
    components = source.get("components")
    if isinstance(components, Mapping) and key in components:
        return components[key]
    return default


def _coerce_float(value: Any) -> float:
    try:
        number = float(value)
    except Exception:
        return 0.0
    if not math.isfinite(number) or number < 0.0:
        return 0.0
    return number


def _normalise_policy_node(
    raw: Mapping[str, Any],
    *,
    default_weights: Mapping[str, float] | None = None,
) -> dict[str, Any] | None:
    node_key = raw.get("node_key")
    if not isinstance(node_key, str) or not node_key:
        return None

    street = str(_extract_component(raw, "street", "unknown"))
    pot_type = str(_extract_component(raw, "pot_type", "single_raised"))
    role = _extract_component(raw, "role", "pfr")
    pos = _extract_component(raw, "pos", "ip")
    texture = str(_extract_component(raw, "texture", "na"))
    spr = str(_extract_component(raw, "spr", "mid"))
    bucket_raw = _extract_component(raw, "bucket", 0)
    try:
        bucket = int(bucket_raw)
    except Exception:
        bucket = bucket_raw

    actions_raw = raw.get("actions")
    if not isinstance(actions_raw, Sequence):
        return None

    actions: list[dict[str, Any]] = []
    weights: list[float] = []
    for entry in actions_raw:
        if not isinstance(entry, Mapping):
            continue
        action_name = entry.get("action")
        if not isinstance(action_name, str) or not action_name:
            continue
        weight_value: Any
        if "weight" in entry:
            weight_value = entry.get("weight")
        elif default_weights is not None and action_name in default_weights:
            weight_value = default_weights[action_name]
        else:
            weight_value = 0.0
        weight = _coerce_float(weight_value)
        actions.append(
            {
                "action": action_name,
                "size_tag": entry.get("size_tag"),
                "weight": weight,
            }
        )
        weights.append(weight)

    if not actions:
        return None

    normalised = _normalize_vector(np.array(weights, dtype=np.float64))
    for idx, value in enumerate(normalised):
        actions[idx]["weight"] = float(value)

    return {
        "node_key": node_key,
        "street": street,
        "pot_type": pot_type,
        "role": role,
        "pos": pos,
        "texture": texture,
        "spr": spr,
        "bucket": bucket,
        "actions": actions,
    }


def _build_policy_nodes(
    tree: Mapping[str, Any],
    hero_node: Mapping[str, Any],
    hero_strategy: Mapping[str, float],
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []

    policy_meta = hero_node.get("policy") if isinstance(hero_node, Mapping) else None
    if isinstance(policy_meta, Mapping):
        hero_node_payload = _normalise_policy_node(policy_meta, default_weights=hero_strategy)
        if hero_node_payload:
            nodes.append(hero_node_payload)

    extra_nodes = tree.get("policy_nodes")
    if isinstance(extra_nodes, Sequence):
        for raw in extra_nodes:
            if isinstance(raw, Mapping):
                node = _normalise_policy_node(raw)
                if node:
                    nodes.append(node)

    return nodes


def _normalize_vector(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, 0.0, None)
    total = float(clipped.sum())
    if total <= 0.0:
        if clipped.size == 0:  # pragma: no cover - defensive
            return clipped
        return np.full_like(clipped, 1.0 / clipped.size)
    return clipped / total


def _normalize_dual(dual: Iterable[float]) -> np.ndarray:
    arr = np.array(list(dual), dtype=np.float64)
    if arr.size == 0:
        return arr
    arr = np.clip(-arr, 0.0, None)
    return _normalize_vector(arr)


def _strictly_dominates_row(candidate: np.ndarray, other: np.ndarray) -> bool:
    return bool(np.all(candidate >= other - NUM_EPS) and np.any(candidate > other + NUM_EPS))


def _strictly_dominates_col(candidate: np.ndarray, other: np.ndarray) -> bool:
    return bool(np.all(candidate <= other + NUM_EPS) and np.any(candidate < other - NUM_EPS))


def _reduce_small_matrix(matrix: np.ndarray) -> tuple[np.ndarray, list[int], list[int], int]:
    reduced = np.array(matrix, copy=True)
    row_indices = list(range(reduced.shape[0]))
    col_indices = list(range(reduced.shape[1]))
    domination_steps = 0

    if reduced.size == 0:
        return reduced, row_indices, col_indices, domination_steps

    while True:
        changed = False

        # Remove duplicate rows
        duplicate_rows: set[int] = set()
        for i in range(len(row_indices)):
            if i in duplicate_rows:
                continue
            for j in range(i + 1, len(row_indices)):
                if np.allclose(reduced[i], reduced[j], atol=NUM_EPS, rtol=0.0):
                    duplicate_rows.add(j)
        if duplicate_rows:
            for idx in sorted(duplicate_rows, reverse=True):
                del row_indices[idx]
                reduced = np.delete(reduced, idx, axis=0)
            domination_steps += len(duplicate_rows)
            changed = True

        # Remove duplicate columns
        duplicate_cols: set[int] = set()
        for i in range(len(col_indices)):
            if i in duplicate_cols:
                continue
            col_i = reduced[:, i]
            for j in range(i + 1, len(col_indices)):
                if np.allclose(col_i, reduced[:, j], atol=NUM_EPS, rtol=0.0):
                    duplicate_cols.add(j)
        if duplicate_cols:
            for idx in sorted(duplicate_cols, reverse=True):
                del col_indices[idx]
                reduced = np.delete(reduced, idx, axis=1)
            domination_steps += len(duplicate_cols)
            changed = True

        # Strictly dominated rows (hero perspective)
        dominated_row: int | None = None
        for i in range(len(row_indices)):
            for j in range(len(row_indices)):
                if i == j:
                    continue
                if _strictly_dominates_row(reduced[j], reduced[i]):
                    dominated_row = i
                    break
            if dominated_row is not None:
                break
        if dominated_row is not None:
            del row_indices[dominated_row]
            reduced = np.delete(reduced, dominated_row, axis=0)
            domination_steps += 1
            changed = True

        # Strictly dominated columns (villain perspective)
        dominated_col: int | None = None
        for i in range(len(col_indices)):
            for j in range(len(col_indices)):
                if i == j:
                    continue
                if _strictly_dominates_col(reduced[:, j], reduced[:, i]):
                    dominated_col = i
                    break
            if dominated_col is not None:
                break
        if dominated_col is not None:
            del col_indices[dominated_col]
            reduced = np.delete(reduced, dominated_col, axis=1)
            domination_steps += 1
            changed = True

        if not changed:
            break

        if reduced.size == 0:
            break

    return reduced, row_indices, col_indices, domination_steps


def _solve_small_matrix(
    matrix: np.ndarray,
) -> tuple[np.ndarray, float, np.ndarray, Any, dict[str, Any]]:
    original_shape = matrix.shape
    reduced, row_indices, col_indices, domination_steps = _reduce_small_matrix(matrix)

    if reduced.size == 0:
        raise LPSolverError("Reduced payoff matrix is empty")

    meta: dict[str, Any] = {
        "method": "linprog_small",
        "reduced_shape": [int(reduced.shape[0]), int(reduced.shape[1])],
        "domination_steps": int(domination_steps),
        "original_shape": [int(original_shape[0]), int(original_shape[1])],
        "hero_index_map": list(row_indices),
        "villain_index_map": list(col_indices),
        "degenerate": False,
        "small_engine_used": True,
    }

    if reduced.shape == (1, 1):
        value = float(reduced[0, 0])
        hero = np.array([1.0], dtype=np.float64)
        villain = np.array([1.0], dtype=np.float64)
        scipy_result = SimpleNamespace(success=True, nit=0, message="small-analytic-1x1")
        meta["method"] = "analytic"
    elif reduced.shape[0] == 1:
        row = reduced[0]
        min_payoff = float(np.min(row))
        mask = np.isclose(row, min_payoff, atol=NUM_EPS)
        villain = _normalize_vector(mask.astype(np.float64))
        hero = np.array([1.0], dtype=np.float64)
        value = float(min_payoff)
        scipy_result = SimpleNamespace(success=True, nit=0, message="small-analytic-1xN")
        meta["method"] = "analytic"
    elif reduced.shape[1] == 1:
        column = reduced[:, 0]
        max_payoff = float(np.max(column))
        mask = np.isclose(column, max_payoff, atol=NUM_EPS)
        hero = _normalize_vector(mask.astype(np.float64))
        villain = np.array([1.0], dtype=np.float64)
        value = float(max_payoff)
        scipy_result = SimpleNamespace(success=True, nit=0, message="small-analytic-Nx1")
        meta["method"] = "analytic"
    elif reduced.shape == (2, 2):
        a, b = float(reduced[0, 0]), float(reduced[0, 1])
        c, d = float(reduced[1, 0]), float(reduced[1, 1])
        denom = a - b - c + d
        if abs(denom) < EPS_DENOM:
            hero, value, villain, scipy_result = _solve_with_linprog(reduced, method="highs")
            meta["degenerate"] = True
        else:
            p = (d - b) / denom
            q = (d - c) / denom
            hero = _normalize_vector(np.array([p, 1.0 - p], dtype=np.float64))
            villain = _normalize_vector(np.array([q, 1.0 - q], dtype=np.float64))
            value = float((a * d - b * c) / denom)
            scipy_result = SimpleNamespace(success=True, nit=0, message="small-analytic-2x2")
            meta["method"] = "analytic"
    else:
        hero, value, villain, scipy_result = _solve_with_linprog(reduced, method="highs")

    return hero, value, villain, scipy_result, meta


def _solve_with_linprog(
    payoff: np.ndarray, *, method: str
) -> tuple[np.ndarray, float, np.ndarray, Any]:
    rows, cols = payoff.shape
    c = np.zeros(rows + 1, dtype=np.float64)
    c[-1] = -1.0

    A_ub = np.zeros((cols, rows + 1), dtype=np.float64)
    for col in range(cols):
        A_ub[col, :rows] = -payoff[:, col]
        A_ub[col, -1] = 1.0
    b_ub = np.zeros(cols, dtype=np.float64)

    A_eq = np.zeros((1, rows + 1), dtype=np.float64)
    A_eq[0, :rows] = 1.0
    b_eq = np.array([1.0], dtype=np.float64)

    bounds = [(0.0, None)] * rows + [(None, None)]

    result = linprog(
        c,
        A_ub=A_ub,
        b_ub=b_ub,
        A_eq=A_eq,
        b_eq=b_eq,
        bounds=bounds,
        method=method,
    )
    if not result.success:
        raise LPSolverError(f"linprog failed: {result.message}")

    hero = np.array(result.x[:rows], dtype=np.float64)
    hero = _normalize_vector(hero)
    value = float(result.x[-1])
    villain = _normalize_dual(getattr(result.ineqlin, "marginals", []))
    return hero, value, villain, result


def _prepare_orders(count: int, seed: int | None) -> list[int]:
    order = list(range(count))
    if seed is None:
        return order
    rng = random.Random(seed)
    rng.shuffle(order)
    return order


def _apply_reorder(
    matrix: np.ndarray, hero_order: list[int], villain_order: list[int]
) -> np.ndarray:
    if hero_order != list(range(len(hero_order))) or villain_order != list(
        range(len(villain_order))
    ):
        return matrix[np.ix_(hero_order, villain_order)]
    return matrix


def _restore_order(vector: np.ndarray, order: list[int]) -> np.ndarray:
    restored = np.zeros_like(vector)
    for shuffled_index, original_index in enumerate(order):
        restored[original_index] = vector[shuffled_index]
    return restored


def _run_highs_backend(
    matrix: np.ndarray, *, require_available: bool
) -> tuple[np.ndarray, float, np.ndarray, Any, dict[str, Any]]:
    meta: dict[str, Any] = {"highspy_imported": False}
    try:
        _import_highspy()
        meta["highspy_imported"] = True
    except ImportError as exc:
        message = (
            f"HiGHS python bindings not available: {exc}"
            if str(exc)
            else "HiGHS python bindings not available"
        )
        meta.setdefault("warnings", []).append(message)
        if require_available:
            raise _BackendUnavailable("HiGHS backend not available") from exc
    hero, value, villain, result = _solve_with_linprog(matrix, method="highs")
    meta.setdefault("solver_impl", "scipy-highs")
    return hero, value, villain, result, meta


def _run_linprog_backend(matrix: np.ndarray) -> tuple[np.ndarray, float, np.ndarray, Any]:
    return _solve_with_linprog(matrix, method="highs")


def solve_lp(
    tree: Mapping[str, Any],
    buckets: Mapping[str, Any],
    transitions: Mapping[str, Any],
    leaf_ev: Mapping[Any, Any],
    *,
    backend: str = "highs",
    seed: int | None = None,
    small_engine: str = "auto",
    small_max_dim: int = 5,
) -> dict[str, Any]:
    """Solve a zero-sum matrix game extracted from the tree artifact."""

    _ensure_mapping(buckets, "buckets")
    _ensure_mapping(transitions, "transitions")
    game = _build_matrix_game(tree, leaf_ev)

    hero_order = _prepare_orders(len(game.hero_actions), seed)
    villain_order = _prepare_orders(len(game.villain_actions), seed if seed is None else seed + 17)
    reordered = _apply_reorder(game.payoff, hero_order, villain_order)

    backend_key = (backend or "auto").lower()
    if backend_key not in {"highs", "linprog", "auto"}:
        raise LPSolverError(f"Unsupported backend '{backend}'")

    small_key = (small_engine or "auto").lower()
    if small_key not in {"auto", "on", "off"}:
        raise LPSolverError(f"Unsupported small engine mode '{small_engine}'")

    max_dim_threshold = max(int(small_max_dim), 1)
    matrix_max_dim = max(reordered.shape)
    use_small_engine = False
    small_meta: dict[str, Any] = {}

    selected = None
    hero_solution: np.ndarray | None = None
    villain_solution: np.ndarray | None = None
    value: float | None = None
    scipy_result: Any | None = None
    backend_meta: dict[str, Any] = {}
    errors: list[str] = []

    if small_key != "off" and matrix_max_dim <= max_dim_threshold:
        try:
            hero_solution, value, villain_solution, scipy_result, small_meta = _solve_small_matrix(
                reordered
            )
            backend_meta.update(small_meta)
            selected = "small"
            use_small_engine = True
        except LPSolverError as exc:
            if small_key == "on":
                raise
            errors.append(f"small engine unavailable: {exc}")
            backend_meta.clear()
    elif small_key == "on" and matrix_max_dim > max_dim_threshold:
        raise LPSolverError(
            f"small engine forced on but matrix dimension {matrix_max_dim} exceeds limit {max_dim_threshold}"
        )

    if not use_small_engine:
        backend_meta.setdefault("small_engine_used", False)
        if backend_key == "highs":
            try:
                hero_solution, value, villain_solution, scipy_result, backend_meta_highs = (
                    _run_highs_backend(reordered, require_available=False)
                )
                backend_meta.update(backend_meta_highs)
                selected = "highs"
            except Exception as exc:  # pragma: no cover - defensive
                raise LPSolverError("HiGHS backend failed") from exc
        elif backend_key == "linprog":
            hero_solution, value, villain_solution, scipy_result = _run_linprog_backend(reordered)
            selected = "linprog"
        else:  # auto
            try:
                hero_solution, value, villain_solution, scipy_result, backend_meta_highs = (
                    _run_highs_backend(reordered, require_available=True)
                )
                backend_meta.update(backend_meta_highs)
                selected = "highs"
            except _BackendUnavailable as exc:
                errors.append(str(exc))
                hero_solution, value, villain_solution, scipy_result = _run_linprog_backend(
                    reordered
                )
                selected = "linprog"
            except Exception as exc:  # pragma: no cover - unexpected failure
                errors.append(f"HiGHS backend failed: {exc}")
                hero_solution, value, villain_solution, scipy_result = _run_linprog_backend(
                    reordered
                )
                selected = "linprog"

    if hero_solution is None or villain_solution is None or value is None or scipy_result is None:
        raise LPSolverError("Solver failed to produce a solution")

    if selected == "small":
        kept_rows = small_meta.get("hero_index_map", list(range(len(hero_order))))
        kept_cols = small_meta.get("villain_index_map", list(range(len(villain_order))))
        hero_expanded = np.zeros(len(hero_order), dtype=np.float64)
        for idx, original in enumerate(kept_rows):
            hero_expanded[original] = hero_solution[idx]
        villain_expanded = np.zeros(len(villain_order), dtype=np.float64)
        for idx, original in enumerate(kept_cols):
            villain_expanded[original] = villain_solution[idx]
        hero_solution = hero_expanded
        villain_solution = villain_expanded
        backend_meta["hero_index_map"] = [hero_order[index] for index in kept_rows]
        backend_meta["villain_index_map"] = [villain_order[index] for index in kept_cols]
        backend_meta["original_action_count_pre_reduction"] = len(hero_order)
        backend_meta["original_response_count_pre_reduction"] = len(villain_order)

    hero_restored = _restore_order(hero_solution, hero_order)
    villain_restored = _restore_order(villain_solution, villain_order)

    hero_dict = {
        name: float(prob) for name, prob in zip(game.hero_actions, hero_restored, strict=False)
    }
    villain_dict = {
        name: float(prob)
        for name, prob in zip(game.villain_actions, villain_restored, strict=False)
    }

    nodes = _build_policy_nodes(tree, game.hero_metadata, hero_dict)
    if nodes and selected == "small":
        hero_node_meta = nodes[0].setdefault("meta", {})
        if backend_meta.get("hero_index_map") is not None:
            hero_node_meta.setdefault("original_index_map", list(backend_meta["hero_index_map"]))
        if backend_meta.get("original_action_count_pre_reduction") is not None:
            hero_node_meta.setdefault(
                "original_action_count_pre_reduction",
                int(backend_meta["original_action_count_pre_reduction"]),
            )
        if backend_meta.get("reduced_shape") is not None:
            hero_node_meta.setdefault("reduced_shape", list(backend_meta["reduced_shape"]))
        if backend_meta.get("domination_steps") is not None:
            hero_node_meta.setdefault("domination_steps", int(backend_meta["domination_steps"]))
        hero_node_meta.setdefault("original_actions", list(game.hero_actions))

    meta = {
        "status": "optimal" if getattr(scipy_result, "success", False) else "failed",
        "message": getattr(scipy_result, "message", ""),
        "iterations": int(getattr(scipy_result, "nit", 0)),
        "objective": float(getattr(scipy_result, "fun", 0.0)),
        "seed": seed,
        "selected_backend": selected,
        "hero_actions": list(game.hero_actions),
        "villain_actions": list(game.villain_actions),
        "warnings": list(errors),
    }
    meta["solver_backend"] = selected
    meta["tree_hash"] = _compute_tree_hash(tree)
    meta["node_count"] = len(nodes)
    meta["lp_value"] = float(value)
    meta.update(backend_meta)
    backend_warnings = backend_meta.get("warnings")
    if backend_warnings:
        meta.setdefault("warnings", []).extend(backend_warnings)

    ineqlin = getattr(scipy_result, "ineqlin", None)
    if ineqlin is not None:
        meta["dual_residual"] = [float(x) for x in getattr(ineqlin, "residual", [])]
        meta["dual_marginals_raw"] = [float(x) for x in getattr(ineqlin, "marginals", [])]
    eqlin = getattr(scipy_result, "eqlin", None)
    if eqlin is not None:
        meta["eq_marginals"] = [float(x) for x in getattr(eqlin, "marginals", [])]

    return {
        "backend": selected,
        "value": float(value),
        "strategy": hero_dict,
        "dual_prices": villain_dict,
        "meta": meta,
        "nodes": nodes,
    }


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as exc:  # pragma: no cover - runtime safeguard
        msg = f"Input file not found: {path}"
        raise LPSolverError(msg) from exc
    except json.JSONDecodeError as exc:
        msg = f"Failed to parse JSON from {path}: {exc}"
        raise LPSolverError(msg) from exc


def _load_tree(path: Path) -> Mapping[str, Any]:
    data = _load_json(path)
    if not isinstance(data, Mapping):
        raise LPSolverError(f"Tree JSON must be a mapping, got {type(data)!r}")
    return data


def _load_directory_json(path: Path) -> dict[str, Any]:
    entries: dict[str, Any] = {}
    for candidate in sorted(path.glob("*.json")):
        if candidate.is_file():
            entries[candidate.stem] = _load_json(candidate)
    if not entries:
        raise LPSolverError(f"Directory {path} does not contain any JSON files")
    return entries


def _load_buckets(path: Path) -> Mapping[str, Any]:
    if path.is_dir():
        return _load_directory_json(path)
    data = _load_json(path)
    if not isinstance(data, Mapping):
        raise LPSolverError(f"Buckets artifact must be a mapping, got {type(data)!r}")
    return data


def _load_transitions(path: Path) -> Mapping[str, Any]:
    if path.is_dir():
        return _load_directory_json(path)
    data = _load_json(path)
    if not isinstance(data, Mapping):
        raise LPSolverError(f"Transitions artifact must be a mapping, got {type(data)!r}")
    return data


def _load_leaf_ev(path: Path) -> Mapping[Any, Any]:
    if path.suffix.lower() == ".npz":
        try:
            with np.load(path, allow_pickle=True) as payload:
                if "leaf_ids" in payload:
                    ids = list(payload["leaf_ids"].tolist())
                    values = list(payload["ev"].tolist()) if "ev" in payload else []
                    if len(ids) != len(values):
                        raise LPSolverError(
                            "leaf_ids and ev arrays must have the same length in NPZ"
                        )
                    return {key: float(val) for key, val in zip(ids, values, strict=False)}
                if "ev" in payload:
                    values = payload["ev"].reshape(-1)
                    return {index: float(val) for index, val in enumerate(values)}
                raise LPSolverError(f"NPZ file {path} does not include an 'ev' or 'leaf_ids' array")
        except FileNotFoundError as exc:  # pragma: no cover - runtime safeguard
            raise LPSolverError(f"Leaf EV NPZ not found: {path}") from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise LPSolverError(f"Failed to load leaf EV NPZ {path}: {exc}") from exc
    data = _load_json(path)
    if isinstance(data, Mapping):
        # Allow JSON-friendly pair keys like "bet|fold" or "bet,fold" as a
        # convenience for CLI usage where tuple keys cannot be expressed.
        normalized: dict[Any, float] = {}
        for raw_key, raw_val in data.items():
            try:
                val_f = float(raw_val)
            except Exception as exc:  # pragma: no cover - defensive
                raise LPSolverError(
                    f"Leaf EV mapping contains non-numeric value for key {raw_key!r}: {raw_val!r}"
                ) from exc

            key: Any = raw_key
            if isinstance(raw_key, str):
                if "|" in raw_key:
                    a, b = raw_key.split("|", 1)
                    key = (a.strip(), b.strip())
                elif "," in raw_key:
                    a, b = raw_key.split(",", 1)
                    key = (a.strip(), b.strip())
                elif "->" in raw_key:
                    a, b = raw_key.split("->", 1)
                    key = (a.strip(), b.strip())
            elif isinstance(raw_key, (list, tuple)) and len(raw_key) == 2:
                key = (str(raw_key[0]), str(raw_key[1]))

            normalized[key] = val_f
        return normalized
    if isinstance(data, Sequence):
        try:
            return {index: float(val) for index, val in enumerate(data)}
        except Exception as exc:  # pragma: no cover - defensive
            raise LPSolverError(f"Leaf EV list contains non-numeric values: {exc}") from exc
    raise LPSolverError(
        f"Unsupported leaf EV artifact type {type(data)!r}; expected mapping, list, or NPZ"
    )


def _write_solution(path: Path, solution: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(solution, indent=2, sort_keys=True))
    tmp_path.replace(path)


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Solve LP for poker tree artifacts")
    parser.add_argument("--tree", required=True, help="Path to tree JSON artifact")
    parser.add_argument(
        "--buckets",
        required=True,
        help="Path to bucket definition (JSON file or directory containing JSON files)",
    )
    parser.add_argument(
        "--transitions",
        required=True,
        help="Path to transition data (JSON file or directory containing JSON files)",
    )
    parser.add_argument(
        "--leaf_ev",
        required=True,
        help="Leaf EV artifact (JSON mapping or NPZ produced by cache_turn_leaf_ev)",
    )
    parser.add_argument("--solver", default="auto", help="Solver backend: auto/highs/linprog")
    parser.add_argument("--seed", type=int, help="Optional random seed for action shuffling")
    parser.add_argument(
        "--small-engine",
        default="auto",
        choices=["auto", "on", "off"],
        help="Enable analytic small-matrix engine (auto/on/off)",
    )
    parser.add_argument(
        "--small-max-dim",
        type=int,
        default=5,
        help="Maximum matrix dimension eligible for small engine",
    )
    parser.add_argument("--out", required=True, help="Output JSON path for solver results")
    parser.add_argument(
        "--log-meta",
        action="store_true",
        help="Emit progress metadata to stderr while solving",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_cli_parser()
    args = parser.parse_args(argv)

    tree_path = Path(args.tree).expanduser().resolve()
    bucket_path = Path(args.buckets).expanduser().resolve()
    transitions_path = Path(args.transitions).expanduser().resolve()
    leaf_path = Path(args.leaf_ev).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()

    start = time.time()
    if args.log_meta:
        print(f"[solve_lp] Loading tree from {tree_path}", flush=True)
    tree = _load_tree(tree_path)

    if args.log_meta:
        print(f"[solve_lp] Loading buckets from {bucket_path}", flush=True)
    buckets = _load_buckets(bucket_path)

    if args.log_meta:
        print(f"[solve_lp] Loading transitions from {transitions_path}", flush=True)
    transitions = _load_transitions(transitions_path)

    if args.log_meta:
        print(f"[solve_lp] Loading leaf EV from {leaf_path}", flush=True)
    leaf_ev = _load_leaf_ev(leaf_path)

    if args.log_meta:
        print(
            f"[solve_lp] Solving LP using backend={args.solver} seed={args.seed}",
            flush=True,
        )
    result = solve_lp(
        tree,
        buckets,
        transitions,
        leaf_ev,
        backend=args.solver,
        seed=args.seed,
        small_engine=args.small_engine,
        small_max_dim=args.small_max_dim,
    )

    duration = time.time() - start
    meta = dict(result.get("meta", {}))
    meta.setdefault("wallclock_seconds", duration)
    meta.setdefault("tree_path", str(tree_path))
    meta.setdefault("buckets_path", str(bucket_path))
    meta.setdefault("transitions_path", str(transitions_path))
    meta.setdefault("leaf_ev_path", str(leaf_path))
    result["meta"] = meta

    if args.log_meta:
        print(
            f"[solve_lp] Writing solution to {out_path} (elapsed {duration:.2f}s)",
            flush=True,
        )
    _write_solution(out_path, result)
    if args.log_meta:
        print("[solve_lp] Completed", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
