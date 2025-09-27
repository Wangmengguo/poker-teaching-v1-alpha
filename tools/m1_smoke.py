"""One-click smoke test for M1 offline artifacts."""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import List, Tuple

from tools import build_buckets, build_tree, cache_turn_leaf_ev, estimate_transitions


REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_CONFIGS = {
    REPO_ROOT / "configs" / "size_map.yaml": "configs/size_map.yaml",
    REPO_ROOT / "configs" / "classifiers.yaml": "configs/classifiers.yaml",
    REPO_ROOT / "configs" / "trees" / "hu_discrete_2cap.yaml": "configs/trees/hu_discrete_2cap.yaml",
}


def _copy_static_configs(workspace: Path) -> None:
    for src, rel in STATIC_CONFIGS.items():
        dest = workspace / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copy2(src, dest)


def _file_size(path: Path) -> str:
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return "missing"
    units = ["B", "KB", "MB"]
    value = float(size)
    unit = 0
    while value >= 1024 and unit < len(units) - 1:
        value /= 1024
        unit += 1
    return f"{value:.1f}{units[unit]}"


def run_smoke(workspace: Path, samples: int, seed: int) -> tuple[bool, List[str]]:
    workspace.mkdir(parents=True, exist_ok=True)
    _copy_static_configs(workspace)

    report_lines: List[str] = []
    durations: List[Tuple[str, float, Path]] = []

    buckets_dir = workspace / "configs" / "buckets"
    transitions_dir = workspace / "artifacts" / "transitions"
    ev_cache_dir = workspace / "artifacts" / "ev_cache"
    tree_out = workspace / "artifacts" / "tree_flat.json"

    transitions_dir.mkdir(parents=True, exist_ok=True)
    ev_cache_dir.mkdir(parents=True, exist_ok=True)

    def timed(label: str, func, path: Path | None = None) -> None:
        start = time.perf_counter()
        func()
        durations.append((label, time.perf_counter() - start, path or Path()))

    try:
        timed(
            "buckets",
            lambda: build_buckets.main(
                [
                    "--streets",
                    "preflop,flop,turn",
                    "--bins",
                    "6,8,8",
                    "--features",
                    "strength,potential",
                    "--out",
                    str(buckets_dir),
                    "--seed",
                    str(seed),
                ]
            ),
            buckets_dir,
        )

        timed(
            "transitions_flop_turn",
            lambda: estimate_transitions.main(
                [
                    "--from",
                    "flop",
                    "--to",
                    "turn",
                    "--samples",
                    str(samples),
                    "--out",
                    str(transitions_dir / "flop_to_turn.json"),
                    "--seed",
                    str(seed),
                ]
            ),
            transitions_dir / "flop_to_turn.json",
        )

        timed(
            "transitions_turn_river",
            lambda: estimate_transitions.main(
                [
                    "--from",
                    "turn",
                    "--to",
                    "river",
                    "--samples",
                    str(samples),
                    "--out",
                    str(transitions_dir / "turn_to_river.json"),
                    "--seed",
                    str(seed),
                ]
            ),
            transitions_dir / "turn_to_river.json",
        )

        timed(
            "tree",
            lambda: build_tree.main(
                [
                    "--config",
                    str(workspace / "configs" / "trees" / "hu_discrete_2cap.yaml"),
                    "--out",
                    str(tree_out),
                ]
            ),
            tree_out,
        )

        timed(
            "turn_ev_cache",
            lambda: cache_turn_leaf_ev.main(
                [
                    "--trans",
                    str(transitions_dir / "turn_to_river.json"),
                    "--out",
                    str(ev_cache_dir / "turn_leaf.npz"),
                    "--seed",
                    str(seed),
                ]
            ),
            ev_cache_dir / "turn_leaf.npz",
        )
    except Exception as exc:  # pragma: no cover - failure path
        report_lines.append(f"FAIL during pipeline: {exc}")
        return False, report_lines

    expected = [
        buckets_dir / "preflop.json",
        buckets_dir / "flop.json",
        buckets_dir / "turn.json",
        transitions_dir / "flop_to_turn.json",
        transitions_dir / "turn_to_river.json",
        tree_out,
        ev_cache_dir / "turn_leaf.npz",
    ]

    missing = [p for p in expected if not p.exists()]
    if missing:
        report_lines.append("Missing artifacts:\n" + "\n".join(str(p) for p in missing))
        return False, report_lines

    report_lines.append("Artifacts summary:")
    for label, duration, path in durations:
        size_display = _file_size(path) if path and path.exists() else "n/a"
        report_lines.append(f"- {label}: {duration:.2f}s, size={size_display}")

    return True, report_lines


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run M1 smoke pipeline")
    parser.add_argument("--out", required=True, help="Path to smoke report (Markdown)")
    parser.add_argument("--quick", action="store_true", help="Use lightweight sample counts")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--workspace",
        default=str(REPO_ROOT),
        help="Workspace root where artifacts/configs will be generated",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    workspace = Path(args.workspace).expanduser().resolve()
    samples = 10_000 if args.quick else 200_000

    start = time.perf_counter()
    ok, details = run_smoke(workspace, samples=samples, seed=args.seed)
    status = "PASS" if ok else "FAIL"
    header = f"{status} — M1 smoke (seed={args.seed}, samples={samples})"
    elapsed = time.perf_counter() - start

    contents = [header, f"Elapsed: {elapsed:.2f}s"] + details
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(contents))
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
