"""End-to-end smoke command for the M2 offline pipeline."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from tools import export_policy
from tools import lp_solver

__all__ = ["run_smoke", "main"]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run M2 smoke pipeline")
    parser.add_argument("--out", required=True, help="Report path")
    parser.add_argument("--workspace", help="Workspace root for artifacts")
    parser.add_argument("--quick", action="store_true", help="Use quick mode")
    parser.add_argument(
        "--reuse", action="store_true", help="Reuse existing artifacts when possible"
    )
    parser.add_argument(
        "--force", action="store_true", help="Force regeneration even if files exist"
    )
    parser.add_argument("--seed", type=int, default=123, help="Random seed passed to solvers")
    return parser.parse_args(argv)


def _toy_tree() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
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
    transitions = {"turn_to_river": [[1.0]]}
    leaf_ev = {
        "leaf_bet_fold": 0.2,
        "leaf_bet_call": -0.1,
        "leaf_check_fold": 0.0,
        "leaf_check_call": 0.05,
    }
    return tree, buckets, transitions, leaf_ev


def _build_solution_dict(result: dict[str, Any], seed: int) -> dict[str, Any]:
    hero_strategy = result.get("strategy", {})
    bet_weight = float(hero_strategy.get("bet", 0.0))
    check_weight = float(hero_strategy.get("check", 0.0))
    postflop_mix = 1.0 - min(max(bet_weight, 0.0), 1.0)

    return {
        "meta": {
            "solver_backend": result.get("backend", "unknown"),
            "seed": seed,
            "tree_hash": "toy-tree-v1",
            "lp_value": result.get("value"),
        },
        "nodes": [
            {
                "node_key": "preflop/single_raised/role:pfr/ip/texture:na/spr:mid/bucket:0",
                "street": "preflop",
                "pot_type": "single_raised",
                "role": "pfr",
                "pos": "ip",
                "texture": "na",
                "spr": "mid",
                "bucket": 0,
                "actions": [
                    {"action": "bet", "size_tag": "2.5x", "weight": bet_weight},
                    {"action": "check", "weight": check_weight},
                ],
            },
            {
                "node_key": "flop/single_raised/role:caller/oop/texture:dry/spr:mid/bucket:4",
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
                "node_key": "turn/single_raised/role:pfr/ip/texture:semi/spr:low/bucket:2",
                "street": "turn",
                "pot_type": "single_raised",
                "role": "pfr",
                "pos": "ip",
                "texture": "semi",
                "spr": "low",
                "bucket": 2,
                "actions": [
                    {"action": "bet", "size_tag": "75", "weight": postflop_mix * 0.5},
                    {"action": "check", "weight": postflop_mix * 0.5 + 0.5},
                ],
            },
        ],
    }


def _maybe_write(path: Path, content: str, *, reuse: bool, force: bool) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if reuse and not force:
            return True
        if not force:
            path.unlink()
    path.write_text(content)
    return False


def run_smoke(
    workspace: Path,
    *,
    quick: bool,
    reuse: bool,
    force: bool,
    seed: int,
) -> tuple[bool, list[str]]:
    if reuse and force:
        raise ValueError("--reuse and --force cannot be combined")

    workspace.mkdir(parents=True, exist_ok=True)
    artifacts_dir = workspace / "artifacts"
    reports_dir = workspace / "reports"
    policies_dir = artifacts_dir / "policies"
    policies_dir.mkdir(parents=True, exist_ok=True)

    report_lines: list[str] = []
    records: list[tuple[str, Path, bool]] = []

    tree, buckets, transitions, leaf_ev = _toy_tree()

    result = lp_solver.solve_lp(tree, buckets, transitions, leaf_ev, backend="auto", seed=seed)
    solution_dict = _build_solution_dict(result, seed)
    solution_path = artifacts_dir / "lp_solution.json"
    reused_solution = _maybe_write(
        solution_path,
        json.dumps(solution_dict, indent=2),
        reuse=reuse,
        force=force,
    )
    records.append(("artifacts/lp_solution.json", solution_path, reused_solution))

    debug_sample = reports_dir / "policy_sample.jsonl"
    export_results = export_policy.export_from_solution(
        solution_dict,
        out_dir=policies_dir,
        compress=False,
        skip_existing=reuse and not force,
        debug_jsonl=(
            debug_sample if not (reuse and (policies_dir / "postflop.npz").exists()) else None
        ),
        solution_path=solution_path,
    )

    for key in ("preflop", "postflop"):
        info = export_results.get(key) or {}
        path = info.get("path", policies_dir / f"{key}.npz")
        records.append((f"artifacts/policies/{key}.npz", path, bool(info.get("reused", False))))

    eval_report = reports_dir / "m2_eval_sample.json"
    sample_stats = {
        "policy_nodes": {k: v.get("node_count", 0) for k, v in export_results.items()},
        "solver_backend": result.get("backend"),
        "quick_mode": quick,
    }
    reused_eval = _maybe_write(
        eval_report,
        json.dumps(sample_stats, indent=2),
        reuse=reuse,
        force=force,
    )
    records.append(("reports/m2_eval_sample.json", eval_report, reused_eval))

    for label, path, reused_flag in records:
        size = path.stat().st_size if path.exists() else 0
        report_lines.append(
            f"artifact: {label} size={size}B reused={'true' if reused_flag else 'false'}"
        )

    report_lines.append(f"solver_backend={result.get('backend')} value={result.get('value'):.6f}")

    return True, report_lines


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    workspace = Path(args.workspace).resolve() if args.workspace else Path.cwd()
    start = time.perf_counter()
    ok, details = run_smoke(
        workspace,
        quick=bool(args.quick),
        reuse=bool(args.reuse),
        force=bool(args.force),
        seed=int(args.seed),
    )
    status = "PASS" if ok else "FAIL"
    elapsed = time.perf_counter() - start

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    contents = [f"{status} — M2 smoke (seed={args.seed}, quick={bool(args.quick)})"]
    contents.append(f"Elapsed: {elapsed:.2f}s")
    contents.extend(details)
    out_path.write_text("\n".join(contents))
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
