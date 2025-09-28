"""Linear program solver wrapper with HiGHS/linprog dual backend support."""

from __future__ import annotations

import importlib
import math
import random
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import linprog

__all__ = ["solve_lp", "LPSolverError"]


class LPSolverError(RuntimeError):
    """Raised when LP construction or backend solving fails."""


@dataclass(slots=True)
class _MatrixGame:
    hero_actions: list[str]
    villain_actions: list[str]
    payoff: np.ndarray


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
    if leaf_id is not None and leaf_id in leaf_ev:
        value = leaf_ev[leaf_id]
    else:
        key = (hero_action, villain_action)
        if key in leaf_ev:
            value = leaf_ev[key]
        else:
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
        node_id = raw_map.get("id")
        if not isinstance(node_id, str):
            raise LPSolverError("Each node must include string id")
        if node_id in node_map:
            raise LPSolverError(f"Duplicate node id detected: {node_id}")
        node_map[node_id] = raw_map

    root_id = tree_map.get("root")
    if root_id is None:
        root_id = nodes[0].get("id")
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

    return _MatrixGame(hero_actions=hero_actions, villain_actions=villain_actions, payoff=matrix)


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

    selected = None
    hero_solution: np.ndarray | None = None
    villain_solution: np.ndarray | None = None
    value: float | None = None
    scipy_result: Any | None = None
    backend_meta: dict[str, Any] = {}
    errors: list[str] = []

    if backend_key == "highs":
        try:
            hero_solution, value, villain_solution, scipy_result, backend_meta = _run_highs_backend(
                reordered, require_available=False
            )
            selected = "highs"
        except Exception as exc:  # pragma: no cover - defensive
            raise LPSolverError("HiGHS backend failed") from exc
    elif backend_key == "linprog":
        hero_solution, value, villain_solution, scipy_result = _run_linprog_backend(reordered)
        selected = "linprog"
    else:  # auto
        try:
            hero_solution, value, villain_solution, scipy_result, backend_meta = _run_highs_backend(
                reordered, require_available=True
            )
            selected = "highs"
        except _BackendUnavailable as exc:
            errors.append(str(exc))
            hero_solution, value, villain_solution, scipy_result = _run_linprog_backend(reordered)
            selected = "linprog"
        except Exception as exc:  # pragma: no cover - unexpected failure
            errors.append(f"HiGHS backend failed: {exc}")
            hero_solution, value, villain_solution, scipy_result = _run_linprog_backend(reordered)
            selected = "linprog"

    if hero_solution is None or villain_solution is None or value is None or scipy_result is None:
        raise LPSolverError("Solver failed to produce a solution")

    hero_restored = _restore_order(hero_solution, hero_order)
    villain_restored = _restore_order(villain_solution, villain_order)

    hero_dict = {
        name: float(prob) for name, prob in zip(game.hero_actions, hero_restored, strict=False)
    }
    villain_dict = {
        name: float(prob)
        for name, prob in zip(game.villain_actions, villain_restored, strict=False)
    }

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
    meta.update(backend_meta)
    backend_warnings = backend_meta.get("warnings")
    if backend_warnings:
        meta.setdefault("warnings", []).extend(backend_warnings)

    ineqlin = getattr(scipy_result, "ineqlin", None)
    if ineqlin is not None:
        meta["dual_residual"] = list(getattr(ineqlin, "residual", []))
        meta["dual_marginals_raw"] = list(getattr(ineqlin, "marginals", []))
    eqlin = getattr(scipy_result, "eqlin", None)
    if eqlin is not None:
        meta["eq_marginals"] = list(getattr(eqlin, "marginals", []))

    return {
        "backend": selected,
        "value": float(value),
        "strategy": hero_dict,
        "dual_prices": villain_dict,
        "meta": meta,
    }
