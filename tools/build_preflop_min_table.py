"""
Build a minimal preflop policy table (NPZ) that matches runtime node_key format.

Node key shape (preflop):
  preflop|<pot_type>|<role>|<pos>|texture=na|spr=<spr>|facing=<facing>|hand=<hand_class>

Covered dimensions (minimal, safe-by-default):
  - pot_type: limped (role=na), single_raised(caller), threebet(pfr|caller)
  - pos: ip|oop
  - facing: third|half|two_third+
  - hand: pair|Ax_suited|suited_broadway|broadway_offsuit|weak

Actions are restricted to: fold/call/raise/allin. Weights are conservative
(caller prefers call over raise; weak prefers fold over call). Size tags are
not used for preflop in our runtime, so set to None.

Usage:
  python tools/build_preflop_min_table.py --out artifacts/policies/preflop.npz
"""

from __future__ import annotations

import argparse
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

POT_TYPES = [
    ("limped", ("na",)),
    ("single_raised", ("caller",)),
    ("threebet", ("pfr", "caller")),
]

POSITIONS = ("ip", "oop")
FACING = ("na", "third", "half", "two_third+")
HANDS = ("pair", "Ax_suited", "suited_broadway", "broadway_offsuit", "weak")


def _weights_for(pot: str, role: str, facing: str, hand: str) -> dict[str, float]:
    # Conservative defaults; top weight points to safest legal action in most preflop states.
    # Special-case: facing=na implies to_call==0 → legal set包含 'check' 而不包含 'call'/'fold'
    if facing == "na":
        # SB first-in (limped pot) 或 BB 允许加注但 to_call==0 的场景
        if pot == "limped":
            if hand in {"pair", "Ax_suited", "suited_broadway"}:
                return {"check": 0.55, "raise": 0.45}
            if hand == "broadway_offsuit":
                return {"check": 0.70, "raise": 0.30}
            return {"check": 0.90, "raise": 0.10}
        # single_raised/threebet 但 to_call==0（BB 可选择加注）
        if hand in {"pair", "Ax_suited", "suited_broadway"}:
            return {"check": 0.70, "raise": 0.30}
        return {"check": 0.95, "raise": 0.05}

    if pot == "limped":
        if hand in {"pair", "Ax_suited", "suited_broadway"}:
            return {"raise": 0.45, "call": 0.45, "fold": 0.10}
        if hand == "broadway_offsuit":
            return {"call": 0.55, "raise": 0.30, "fold": 0.15}
        return {"call": 0.60, "fold": 0.40}

    if pot == "single_raised" and role == "caller":
        if facing == "third":
            if hand in {"pair", "Ax_suited", "suited_broadway"}:
                return {"call": 0.70, "raise": 0.10, "fold": 0.20}
            if hand == "broadway_offsuit":
                return {"call": 0.60, "fold": 0.40}
            return {"call": 0.55, "fold": 0.45}
        if facing == "half":
            if hand in {"pair", "Ax_suited", "suited_broadway"}:
                return {"call": 0.60, "fold": 0.40}
            return {"fold": 0.60, "call": 0.40}
        # two_third+
        if hand in {"pair", "Ax_suited"}:  # tighter
            return {"call": 0.55, "fold": 0.45}
        return {"fold": 0.70, "call": 0.30}

    if pot == "threebet":
        # Default: caller更偏向跟注，pfr更偏向弃牌/少量四bet
        if role == "caller":
            if hand in {"pair", "Ax_suited", "suited_broadway"}:
                return {"call": 0.60, "fold": 0.30, "raise": 0.10}
            if hand == "broadway_offsuit":
                return {"call": 0.50, "fold": 0.50}
            return {"fold": 0.70, "call": 0.30}
        else:  # pfr facing 3bet
            if hand == "pair":
                return {"raise": 0.20, "call": 0.40, "fold": 0.40}
            if hand in {"Ax_suited", "suited_broadway"}:
                return {"call": 0.45, "fold": 0.45, "raise": 0.10}
            return {"fold": 0.70, "call": 0.30}

    # Fallback
    return {"call": 0.50, "fold": 0.50}


def _build_nodes() -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for pot, roles in POT_TYPES:
        for role in roles:
            for pos in POSITIONS:
                for fac in FACING:
                    for hand in HANDS:
                        node_key = "|".join(
                            [
                                "preflop",
                                pot,
                                role,
                                pos,
                                "texture=na",
                                "spr=na",
                                f"facing={fac}",
                                f"hand={hand}",
                            ]
                        )
                        dist = _weights_for(pot, role, fac, hand)
                        actions = tuple(dist.keys())
                        weights = tuple(float(v) for v in dist.values())
                        size_tags = tuple(None for _ in actions)
                        comp = {
                            "street": "preflop",
                            "pot_type": pot,
                            "role": f"role:{role}" if role not in {"na"} else "role:na",
                            "pos": pos,
                            "texture": "na",
                            "spr": "na",
                            "facing": fac,
                            "bucket": "-1",
                        }
                        meta = {
                            "node_key": node_key,
                            "node_key_components": comp,
                            "actions": list(actions),
                            "size_tags": list(size_tags),
                            "weights": list(weights),
                            "zero_weight_actions": [],
                            "node_meta": {"source": "preflop_min_builder"},
                        }
                        nodes.append(
                            {
                                "node_key": node_key,
                                "components": comp,
                                "actions": actions,
                                "size_tags": size_tags,
                                "weights": weights,
                                "meta": meta,
                            }
                        )
    return nodes


def build(out_path: Path) -> dict[str, Any]:
    nodes = _build_nodes()
    # Normalise to arrays compatible with runtime loader
    node_keys = np.array([n["node_key"] for n in nodes], dtype=object)
    actions = np.array([tuple(n["actions"]) for n in nodes], dtype=object)
    weights = np.array([tuple(n["weights"]) for n in nodes], dtype=object)
    size_tags = np.array([tuple(n["size_tags"]) for n in nodes], dtype=object)
    meta = np.array([n["meta"] for n in nodes], dtype=object)
    table_meta = np.array(
        [
            {
                "generated_at": datetime.now(tz=UTC).isoformat(),
                "solver_backend": "manual_min",
                "seed": None,
                "tree_hash": None,
                "source_solution": None,
                "street": "preflop",
                "node_count": len(nodes),
            }
        ],
        dtype=object,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        out_path,
        node_keys=node_keys,
        actions=actions,
        weights=weights,
        size_tags=size_tags,
        meta=meta,
        table_meta=table_meta,
    )
    return {"out": str(out_path), "node_count": len(nodes)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build minimal preflop policy table")
    ap.add_argument("--out", required=True, help="Output preflop npz path")
    args = ap.parse_args(argv)
    res = build(Path(args.out))
    print(f"Wrote preflop table to {res['out']} (nodes={res['node_count']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
