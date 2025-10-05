"""Export solved policies into NPZ tables for runtime lookup."""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Mapping
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

__all__ = ["export_from_solution", "main"]

_EPS = 1e-9


class PolicyExportError(RuntimeError):
    """Raised when the policy export pipeline encounters invalid data."""


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export solved policies to NPZ tables")
    parser.add_argument("--solution", required=True, help="Path to solver solution JSON")
    parser.add_argument("--out", required=True, help="Output directory for NPZ policies")
    parser.add_argument("--debug-jsonl", help="Optional debug JSONL output path")
    parser.add_argument("--compress", action="store_true", help="Use np.savez_compressed")
    parser.add_argument(
        "--reuse",
        action="store_true",
        help="Skip writing files that already exist (used by orchestration tools)",
    )
    return parser.parse_args(argv)


def _load_solution(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except Exception as exc:  # pragma: no cover - defensive
        raise PolicyExportError(f"Failed to read solution file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PolicyExportError("Solution file must contain an object")
    return data


def _normalise_weight(value: Any) -> float:
    try:
        weight = float(value)
    except Exception:
        return 0.0
    if not math.isfinite(weight) or weight < 0:
        return 0.0
    return weight


def _ensure_role(role: Any) -> str:
    if isinstance(role, str) and role.startswith("role:"):
        return role
    if isinstance(role, str) and role:
        return f"role:{role}"
    return "role:na"


def _split_node_key(node_key: str) -> list[str]:
    if "|" in node_key:
        return node_key.split("|")
    return node_key.split("/")


def _extract_dimension(parts: list[str], key: str, default: str) -> str:
    prefixes = (f"{key}:", f"{key}=")
    for part in parts:
        for prefix in prefixes:
            if part.startswith(prefix):
                remainder = part[len(prefix) :]
                return remainder or default
    return default


def _build_components(raw: Mapping[str, Any], node_key: str) -> dict[str, Any]:
    parts = _split_node_key(node_key) if node_key else []
    street = str(raw.get("street") or (parts[0] if parts else "unknown"))
    pot_type = str(raw.get("pot_type") or (parts[1] if len(parts) > 1 else "single_raised"))
    role = _ensure_role(raw.get("role") or (parts[2] if len(parts) > 2 else "role:na"))
    pos = str(raw.get("pos") or (parts[3] if len(parts) > 3 else "na"))
    texture = str(raw.get("texture") or _extract_dimension(parts, "texture", "na"))
    spr = str(raw.get("spr") or _extract_dimension(parts, "spr", "na"))
    facing_value = raw.get("facing")
    if facing_value is None:
        facing_value = _extract_dimension(parts, "facing", "na")
    bucket_value = raw.get("bucket")
    if bucket_value is None:
        bucket_value = _extract_dimension(parts, "bucket", "-1")
    return {
        "street": street,
        "pot_type": pot_type,
        "role": role,
        "pos": pos,
        "texture": texture,
        "spr": spr,
        "facing": str(facing_value),
        "bucket": str(bucket_value),
    }


def _normalise_node(raw: Mapping[str, Any], *, index: int) -> dict[str, Any]:
    node_key = str(raw.get("node_key") or "")
    if not node_key:
        raise PolicyExportError(f"Node #{index} missing node_key")

    actions_raw = raw.get("actions") or []
    if not isinstance(actions_raw, list):
        raise PolicyExportError(f"Node {node_key} actions must be a list")

    actions: list[str] = []
    weights_raw: list[float] = []
    size_tags: list[str | None] = []
    for arm in actions_raw:
        if not isinstance(arm, dict):
            continue
        action_name = arm.get("action")
        if not isinstance(action_name, str) or not action_name:
            continue
        actions.append(action_name)
        weights_raw.append(_normalise_weight(arm.get("weight")))
        size_tag = arm.get("size_tag")
        size_tags.append(str(size_tag) if size_tag is not None else None)

    if not actions:
        raise PolicyExportError(f"Node {node_key} contains no valid actions")

    total = sum(weights_raw)
    if total <= _EPS:
        weights = [1.0 if i == 0 else 0.0 for i in range(len(actions))]
    else:
        weights = [w / total for w in weights_raw]

    zero_weight_actions = [a for a, w in zip(actions, weights, strict=False) if w <= _EPS]
    components = _build_components(raw, node_key)
    components_facing = str(components.get("facing") or "na")

    raw_meta = raw.get("meta") if isinstance(raw.get("meta"), Mapping) else {}
    meta_flags: dict[str, Any] = dict(raw_meta)

    fallback_from_raw = meta_flags.get("fallback_from")
    if isinstance(fallback_from_raw, list):
        fallback_from = [str(item) for item in fallback_from_raw]
    elif fallback_from_raw is None:
        fallback_from = []
    else:
        fallback_from = [str(fallback_from_raw)]

    facing_present = "facing" in raw and raw.get("facing") not in {None, ""}
    if facing_present:
        components["facing"] = str(raw.get("facing"))
        meta_flags.setdefault("facing_fallback", False)
    else:
        if components_facing not in {"", "na"} and components_facing not in fallback_from:
            fallback_from.append(components_facing)
        components["facing"] = "na"
        meta_flags["facing_fallback"] = True

    meta_flags["fallback_from"] = fallback_from
    meta_flags.setdefault("facing_fallback", False)

    return {
        "node_key": node_key,
        "components": components,
        "actions": actions,
        "size_tags": size_tags,
        "weights": weights,
        "zero_weight_actions": zero_weight_actions,
        "meta": meta_flags,
    }


def _partition_nodes(nodes: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {"preflop": [], "postflop": []}
    for node in nodes:
        street = node["components"]["street"].lower()
        target = "preflop" if street == "preflop" else "postflop"
        buckets[target].append(node)
    return buckets


def _write_npz(
    out_path: Path,
    *,
    nodes: list[dict[str, Any]],
    compress: bool,
    skip_existing: bool,
    table_meta: dict[str, Any],
) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if skip_existing and out_path.exists():
        return True

    node_keys = np.array([node["node_key"] for node in nodes], dtype=object)
    actions = np.array([tuple(node["actions"]) for node in nodes], dtype=object)
    weights = np.array([tuple(node["weights"]) for node in nodes], dtype=object)
    size_tags = np.array([tuple(node["size_tags"]) for node in nodes], dtype=object)
    meta = np.array(
        [
            {
                "node_key": node["node_key"],
                "node_key_components": node["components"],
                "actions": node["actions"],
                "size_tags": node["size_tags"],
                "weights": node["weights"],
                "zero_weight_actions": node["zero_weight_actions"],
                "node_meta": node.get("meta", {}),
            }
            for node in nodes
        ],
        dtype=object,
    )
    table_meta_array = np.array([table_meta], dtype=object)

    save_fn = np.savez_compressed if compress else np.savez
    save_fn(
        out_path,
        node_keys=node_keys,
        actions=actions,
        weights=weights,
        size_tags=size_tags,
        meta=meta,
        table_meta=table_meta_array,
    )
    return False


def _write_debug_jsonl(
    path: Path, entries: list[dict[str, Any]], table_meta: dict[str, Any]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"table_meta": table_meta}) + "\n")
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")


def export_from_solution(
    solution: dict[str, Any],
    *,
    out_dir: Path,
    compress: bool = False,
    skip_existing: bool = False,
    debug_jsonl: Path | None = None,
    solution_path: Path | None = None,
) -> dict[str, Any]:
    raw_nodes = solution.get("nodes")
    if not isinstance(raw_nodes, list):
        raise PolicyExportError("Solution file missing 'nodes' list")

    normalised = [_normalise_node(raw, index=i) for i, raw in enumerate(raw_nodes)]
    normalised.sort(key=lambda node: node["node_key"])  # deterministic ordering
    partitions = _partition_nodes(normalised)

    meta_src = solution.get("meta") if isinstance(solution.get("meta"), dict) else {}
    generated_at = datetime.now(tz=UTC).isoformat()
    table_meta_common = {
        "generated_at": generated_at,
        "solver_backend": meta_src.get("solver_backend", "unknown"),
        "seed": meta_src.get("seed"),
        "tree_hash": meta_src.get("tree_hash"),
        "source_solution": str(solution_path) if solution_path else None,
    }

    results: dict[str, Any] = {}
    for street_key, nodes in partitions.items():
        out_path = out_dir / f"{street_key}.npz"
        table_meta = dict(table_meta_common)
        table_meta["street"] = street_key
        table_meta["node_count"] = len(nodes)
        reused = _write_npz(
            out_path,
            nodes=nodes,
            compress=compress,
            skip_existing=skip_existing,
            table_meta=table_meta,
        )
        if debug_jsonl and street_key == "postflop" and not (skip_existing and out_path.exists()):
            # Limit debug export to postflop to avoid large files in tests
            _write_debug_jsonl(debug_jsonl, nodes[:10], table_meta)
        results[street_key] = {
            "path": out_path,
            "reused": reused,
            "node_count": len(nodes),
            "table_meta": table_meta,
        }

    return results


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    solution_path = Path(args.solution)
    out_dir = Path(args.out)
    solution = _load_solution(solution_path)

    export_from_solution(
        solution,
        out_dir=out_dir,
        compress=bool(args.compress),
        skip_existing=bool(args.reuse),
        debug_jsonl=Path(args.debug_jsonl) if args.debug_jsonl else None,
        solution_path=solution_path,
    )
    return 0
