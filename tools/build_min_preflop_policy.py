"""
Build a minimal preflop NPZ table that only covers HU BB facing SB open
in single-raised pots (role=caller, pos=ip), with facing buckets
{third, half, two_third+} × hand={pair, Ax_suited, suited_broadway,
broadway_offsuit, weak}. Actions are {call, fold} only.

This table is designed to be safe: it does NOT cover first-in (role=na)
or raise sizing, so it won't override your open/3bet sizing rules.

Usage:
  python tools/build_min_preflop_policy.py \
    --out artifacts/policies/preflop_addon.npz --compress
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

HAND_CLASSES = [
    "pair",
    "Ax_suited",
    "suited_broadway",
    "broadway_offsuit",
    "weak",
]

FACING = ["third", "half", "two_third+"]


def _dist(call_weight: float) -> tuple[tuple[str, ...], tuple[float, ...]]:
    call_w = max(0.0, min(1.0, float(call_weight)))
    fold_w = 1.0 - call_w
    return ("call", "fold"), (call_w, fold_w)


def _call_weight_for(hand: str, facing: str) -> float:
    # Simple monotone grid: larger facing → lower call freq; stronger class → higher call freq.
    base = {
        "pair": 0.85,
        "Ax_suited": 0.70,
        "suited_broadway": 0.60,
        "broadway_offsuit": 0.40,
        "weak": 0.10,
    }[hand]
    facing_penalty = {"third": 0.00, "half": 0.10, "two_third+": 0.25}[facing]
    return max(0.0, min(1.0, base - facing_penalty))


def _node_key(hand: str, facing: str) -> str:
    # HU, BB vs SB open → single_raised | caller | ip
    return "|".join(
        [
            "preflop",
            "single_raised",
            "caller",
            "ip",
            "texture=na",
            "spr=na",
            f"facing={facing}",
            f"hand={hand}",
        ]
    )


def _components(hand: str, facing: str) -> dict[str, Any]:
    return {
        "street": "preflop",
        "pot_type": "single_raised",
        "role": "caller",
        "pos": "ip",
        "texture": "na",
        "spr": "na",
        "facing": facing,
        "bucket": "-1",
        "hand": hand,
    }


def build_table() -> dict[str, Any]:
    node_keys: list[str] = []
    actions: list[tuple[str, ...]] = []
    weights: list[tuple[float, ...]] = []
    size_tags: list[tuple[str | None, ...]] = []
    meta_list: list[Any] = []

    for facing in FACING:
        for hand in HAND_CLASSES:
            key = _node_key(hand, facing)
            node_keys.append(key)
            acts, w = _dist(_call_weight_for(hand, facing))
            actions.append(acts)
            weights.append(w)
            size_tags.append(tuple(None for _ in acts))
            meta_list.append(
                {
                    "node_key": key,
                    "node_key_components": _components(hand, facing),
                    "actions": list(acts),
                    "size_tags": [None for _ in acts],
                    "weights": list(w),
                    "zero_weight_actions": [a for a, ww in zip(acts, w) if ww <= 0.0],
                    "node_meta": {},
                }
            )

    table_meta = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "solver_backend": "manual_min_preflop",
        "seed": None,
        "tree_hash": None,
        "source_solution": None,
        "street": "preflop",
        "node_count": len(node_keys),
    }

    return {
        "node_keys": np.array(node_keys, dtype=object),
        "actions": np.array(actions, dtype=object),
        "weights": np.array(weights, dtype=object),
        "size_tags": np.array(size_tags, dtype=object),
        "meta": np.array(meta_list, dtype=object),
        "table_meta": np.array([table_meta], dtype=object),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build minimal preflop table")
    ap.add_argument("--out", required=True, help="Output npz path")
    ap.add_argument("--compress", action="store_true")
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    data = build_table()
    save = np.savez_compressed if args.compress else np.savez
    save(out, **data)
    print(
        json.dumps(
            {"out": str(out), "node_count": int(data["table_meta"][0].item().get("node_count", 0))}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
