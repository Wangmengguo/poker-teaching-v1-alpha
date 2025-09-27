"""Approximate turn leaf EV cache generator.

Derives a deterministic EV vector for each turn bucket using the transition
matrix as a weighting function. Intended as a placeholder until solver outputs
are integrated in later milestones.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np


def _load_transition(path: Path) -> dict:
    data = json.loads(path.read_text())
    required = {"matrix", "from_bins", "to_bins", "meta"}
    if not required <= data.keys():
        missing = required - data.keys()
        raise ValueError(f"transition artifact missing keys: {missing}")
    return data


def generate_turn_leaf_ev(
    transition_path: Path,
    seed: int = 42,
) -> tuple[np.ndarray, dict]:
    trans = _load_transition(transition_path)
    matrix = np.array(trans["matrix"], dtype=np.float64)
    from_bins = int(trans.get("from_bins"))
    to_bins = int(trans.get("to_bins"))

    if matrix.shape != (from_bins, to_bins):
        raise ValueError("matrix shape does not match metadata")

    rng = random.Random(seed)
    base_vector = np.linspace(0.15, 0.85, to_bins, dtype=np.float64)
    # inject a small deterministic jitter per bucket based on seed to avoid flat outputs
    noise_vector = np.array([(rng.random() - 0.5) * 0.04 for _ in range(to_bins)])
    weighted_vector = np.clip(base_vector + noise_vector, 0.0, 1.0)

    ev = matrix @ weighted_vector
    ev = np.clip(ev, 0.0, 1.0).astype(np.float32)

    meta = {
        "derived_from_turn_leaf": True,
        "seed": seed,
        "source_transition": str(transition_path),
        "samples": trans.get("meta", {}).get("samples"),
        "hero_range": trans.get("meta", {}).get("hero_range"),
        "villain_range": trans.get("meta", {}).get("villain_range"),
        "board_sampler": trans.get("meta", {}).get("board_sampler"),
        "conditioners": trans.get("meta", {}).get("conditioners"),
    }
    return ev, meta


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cache turn leaf EV approximations")
    parser.add_argument("--trans", required=True, help="Path to transition JSON artifact")
    parser.add_argument("--out", required=True, help="Output NPZ path")
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args(argv)


def write_cache(ev: np.ndarray, meta: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ev": ev,
        "meta": np.array(json.dumps(meta)),
    }
    np.savez(path, **payload)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    ev, meta = generate_turn_leaf_ev(Path(args.trans), seed=args.seed)
    write_cache(ev, meta, Path(args.out))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
