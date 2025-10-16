"""
Augment exported NPZ policy tables with minimally required branches.

Currently supported:
- Add threebet-pot mirrors for all postflop nodes by copying single_raised
  entries and replacing pot_type.

Run:
  python tools/augment_policy_tables.py --in artifacts/policies/postflop.npz \
    --out artifacts/policies/postflop.npz

This will load the NPZ, create missing threebet nodes, and save back.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np


def _load_npz(path: Path) -> dict[str, Any]:
    with np.load(path, allow_pickle=True) as z:
        return {k: z[k] for k in z.files}


def _save_npz(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, **payload)


def _replace_component(node_key: str, key: str, value: str) -> str:
    parts = node_key.split("|")
    updated: list[str] = []
    seen = False
    prefix = f"{key}="
    for p in parts:
        if p == "threebet" and key == "pot_type":
            seen = True
            updated.append("threebet")
            continue
        if p.startswith(prefix):
            seen = True
            updated.append(f"{key}={value}")
        else:
            updated.append(p)
    if not seen:
        # insert after street
        if parts:
            updated = [parts[0], value] + parts[1:]
        else:
            updated = [value]
    return "|".join(updated)


def _infer_pot_type_fragment(node_key: str) -> str:
    # Accept both token style ("single_raised") and component style ("pot_type=single_raised")
    if "|single_raised|" in f"|{node_key}|":
        return "single_raised"
    if "|threebet|" in f"|{node_key}|":
        return "threebet"
    for seg in node_key.split("|"):
        if seg.startswith("pot_type="):
            return seg.split("=", 1)[1]
    return "single_raised"


def augment_threebet_postflop(in_path: Path, out_path: Path) -> dict[str, int]:
    data = _load_npz(in_path)
    keys = list(map(str, data.get("node_keys", [])))
    actions = list(data.get("actions", []))
    weights = list(data.get("weights", []))
    size_tags = list(data.get("size_tags", []))
    meta_arr = list(data.get("meta", []))
    table_meta = list(data.get("table_meta", []))

    seen = set(keys)
    added = 0

    for i, k in enumerate(keys):
        pot = _infer_pot_type_fragment(k)
        if pot != "single_raised":
            continue
        k3 = k.replace("|single_raised|", "|threebet|")
        if k3 == k or k3 in seen:
            continue
        # Duplicate entry with updated node_key & components meta
        keys.append(k3)
        actions.append(actions[i])
        weights.append(weights[i])
        size_tags.append(size_tags[i])
        # Update embedded meta copy
        m = meta_arr[i].item() if hasattr(meta_arr[i], "item") else dict(meta_arr[i])
        m2 = dict(m)
        # update node_key and components
        m2["node_key"] = k3
        comp = dict(m2.get("node_key_components", {}))
        if comp:
            comp["pot_type"] = "threebet"
            m2["node_key_components"] = comp
        meta_arr.append(np.array(m2, dtype=object))
        added += 1

    # Rebuild arrays
    payload = {
        "node_keys": np.array(keys, dtype=object),
        "actions": np.array(actions, dtype=object),
        "weights": np.array(weights, dtype=object),
        "size_tags": np.array(size_tags, dtype=object),
        "meta": np.array(meta_arr, dtype=object),
        "table_meta": np.array(table_meta, dtype=object),
    }
    _save_npz(out_path, payload)
    return {"added": added, "total": len(keys)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Augment postflop NPZ policies")
    ap.add_argument("--in", dest="in_path", required=True)
    ap.add_argument("--out", dest="out_path", required=True)
    args = ap.parse_args()
    res = augment_threebet_postflop(Path(args.in_path), Path(args.out_path))
    print(f"Augmented threebet nodes: +{res['added']} (total {res['total']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
