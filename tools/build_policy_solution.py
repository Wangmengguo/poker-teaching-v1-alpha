"""Synthesize a policy solution JSON that covers runtime node keys.

This utility enumerates a grid of node keys across street/pot_type/role/pos/
texture/spr/hand_class based on the repository configs and assigns heuristic
action mixes. The output format matches what tools.export_policy expects:

{
  "meta": {"solver_backend": "heuristic", "seed": 123, ...},
  "nodes": [
    {
      "node_key": "flop|single_raised|pfr|ip|texture=dry|spr=spr4|facing=na|hand=overpair_or_tptk",
      "street": "flop",
      "pot_type": "single_raised",
      "role": "pfr",
      "pos": "ip",
      "texture": "dry",
      "spr": "spr4",
      "bucket": "na",
      "actions": [
        {"action": "bet", "size_tag": "third", "weight": 0.6},
        {"action": "check", "weight": 0.4}
      ]
    },
    ...
  ]
}
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

FACING_TAGS = ["third", "half", "two_third+"]

DEFAULT_FACING_WEIGHTS: dict[str, dict[str, Any]] = {
    "third": {
        "call": 0.55,
        "fold": 0.30,
        "raise": {"weight": 0.15, "size_tag": "half"},
    },
    "half": {
        "call": 0.40,
        "fold": 0.50,
        "raise": {"weight": 0.10, "size_tag": "half"},
    },
    "two_third+": {
        "call": 0.20,
        "fold": 0.70,
        "raise": {"weight": 0.10, "size_tag": "half"},
    },
}


def _ensure_meta(node: dict[str, Any]) -> dict[str, Any]:
    meta = node.setdefault("meta", {})
    if not isinstance(meta, dict):
        meta = {}
        node["meta"] = meta
    meta.setdefault("facing_fallback", False)
    meta.setdefault("fallback_from", [])
    return meta


def _record_fallback(node: dict[str, Any], facing: str) -> None:
    meta = _ensure_meta(node)
    meta["facing_fallback"] = True
    fallback_from = meta.setdefault("fallback_from", [])
    if facing not in fallback_from:
        fallback_from.append(facing)


def _sanitise_mix(call: float, fold: float, raise_w: float) -> list[float]:
    values = [
        max(float(call or 0.0), 0.0),
        max(float(fold or 0.0), 0.0),
        max(float(raise_w or 0.0), 0.0),
    ]
    total = sum(values)
    if total <= 0.0:
        return [0.5, 0.4, 0.1]
    return [v / total for v in values]


def _resolve_facing_overrides(
    classifiers: dict[str, Any], manifest: dict[str, Any]
) -> tuple[dict[str, Any], bool]:
    if isinstance(manifest.get("facing_defaults"), dict):
        return manifest["facing_defaults"], True
    weights = classifiers.get("facing_weights")
    if isinstance(weights, dict):
        return weights, True
    return {}, False


def _defence_actions(
    facing: str,
    overrides: dict[str, Any],
    *,
    overrides_provided: bool,
) -> tuple[list[dict[str, Any]] | None, bool]:
    config = overrides.get(facing)
    if config is None:
        if overrides_provided:
            return None, True
        config = DEFAULT_FACING_WEIGHTS.get(facing)

    if not isinstance(config, dict):
        return None, True

    call = config.get("call", 0.0)
    fold = config.get("fold", 0.0)
    raise_cfg = config.get("raise", {})
    if not isinstance(raise_cfg, dict):
        raise_cfg = {}
    raise_weight = raise_cfg.get("weight", 0.0)
    size_tag = str(raise_cfg.get("size_tag") or "half")

    call_w, fold_w, raise_w = _sanitise_mix(call, fold, raise_weight)
    actions = [
        {"action": "call", "weight": call_w},
        {"action": "fold", "weight": fold_w},
        {"action": "raise", "weight": raise_w, "size_tag": size_tag},
    ]
    return actions, False


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
    except Exception:
        data = None
    return data if isinstance(data, dict) else {}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        raise RuntimeError(f"Failed to read JSON from {path}: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _bucket_labels(path: Path) -> list[str]:
    data = _load_json(path)
    labels = data.get("labels")
    if not isinstance(labels, list):
        return []
    return [str(x) for x in labels]


def _spr_labels(classifiers: dict[str, Any]) -> list[str]:
    bins = classifiers.get("spr_bins", {}).get("bins", [])
    out: list[str] = []
    if isinstance(bins, list):
        for item in bins:
            if isinstance(item, dict) and item.get("label"):
                out.append(str(item["label"]))
    # Include NA bucket when present
    na_alias = classifiers.get("spr_bins", {}).get("na_label")
    if na_alias:
        out.insert(0, str(na_alias))
    else:
        out.insert(0, "na")
    return out


def _texture_labels(classifiers: dict[str, Any]) -> list[str]:
    cfg = classifiers.get("texture", {})
    aliases = cfg.get("aliases", {}) if isinstance(cfg, dict) else {}
    # Keep canonical order: dry, semi, wet; ensure 'na' exists for preflop
    base = ["dry", "semi", "wet"]
    out = [x for x in base if x in (aliases or {x: [x] for x in base})]
    out.insert(0, "na")
    return out


def _bet_check_mix(hand: str, texture: str, spr: str) -> tuple[float, str]:
    """Return (bet_weight, size_tag) for postflop no-bet-yet nodes.

    Simple heuristics:
      - Strong value -> bet heavy, size increases with texture wetness and lower SPR
      - Strong draw -> bet; weak draw -> some bet on wet/semi
      - Air/overcards -> check heavy
    """

    hand_key = str(hand).lower()
    texture_key = str(texture).lower()
    spr_key = str(spr).lower()

    # Base sizes and weights by class
    size_tag = "third"
    if hand_key in {"value_two_pair_plus"}:
        w = 0.85
        size_tag = "half"
    elif hand_key in {"overpair_or_tptk"}:
        w = 0.65
        size_tag = "third"
    elif hand_key in {"top_pair_weak_or_second"}:
        w = 0.55
        size_tag = "third"
    elif hand_key in {"middle_pair_or_third_minus"}:
        w = 0.35
        size_tag = "third"
    elif hand_key in {"strong_draw"}:
        w = 0.6
        size_tag = "two_third"
    elif hand_key in {"weak_draw"}:
        w = 0.45
        size_tag = "third"
    elif hand_key in {"overcards_no_bdfd", "air"}:
        w = 0.15
        size_tag = "third"
    else:
        # Unknown class: neutral mix
        w = 0.5
        size_tag = "third"

    # Texture adjustment: wet -> increase betting; dry -> decrease slightly
    if texture_key == "wet":
        w += 0.1
        if hand_key in {"value_two_pair_plus", "strong_draw"}:
            size_tag = "two_third"
    elif texture_key == "dry":
        w -= 0.05

    # SPR adjustment: low SPR (spr2/spr4) encourages betting; high SPR dampens
    if spr_key in {"spr2", "spr4"}:
        w += 0.08
    elif spr_key in {"spr8", "spr10"}:
        w -= 0.04

    return max(0.0, min(1.0, w)), size_tag


def _preflop_mix(hand: str) -> tuple[float, float, float, str | None]:
    """Return (raise, call, fold, size_tag) for preflop buckets."""

    key = str(hand).lower()
    if key == "premium_pair":
        return 0.92, 0.08, 0.0, "open_2.5bb"
    if key == "strong_broadway":
        return 0.65, 0.35, 0.0, "open_2.5bb"
    if key == "suited_ace":
        return 0.55, 0.45, 0.0, "open_2.5bb"
    if key == "medium_pair":
        return 0.5, 0.5, 0.0, "open_2.5bb"
    if key == "suited_connectors":
        return 0.45, 0.55, 0.0, "open_2.5bb"
    if key == "junk":
        return 0.05, 0.15, 0.8, None
    # Default neutral
    return 0.5, 0.4, 0.1, "open_2.5bb"


def build_solution_from_configs(workspace: Path, *, seed: int = 123) -> dict[str, Any]:
    configs_dir = workspace / "configs"
    classifiers = _load_yaml(configs_dir / "classifiers.yaml")
    sprs = _spr_labels(classifiers)
    textures = _texture_labels(classifiers)

    pf_labels = _bucket_labels(configs_dir / "buckets" / "preflop.json")
    fl_labels = _bucket_labels(configs_dir / "buckets" / "flop.json")
    tu_labels = _bucket_labels(configs_dir / "buckets" / "turn.json")
    rv_labels = (
        list(tu_labels)
        if tu_labels
        else [
            "value_two_pair_plus",
            "overpair_or_tptk",
            "top_pair_weak_or_second",
            "middle_pair_or_third_minus",
            "strong_draw",
            "weak_draw",
            "overcards_no_bdfd",
            "air",
        ]
    )

    nodes: list[dict[str, Any]] = []

    # Preflop: single_raised, texture/spr NA
    for role in ("pfr", "caller"):
        for pos in ("ip", "oop"):
            for hand in pf_labels:
                r, c, f, tag = _preflop_mix(hand)
                node_key = "|".join(
                    [
                        "preflop",
                        "single_raised",
                        role,
                        pos,
                        "texture=na",
                        "spr=na",
                        "facing=na",
                        f"hand={hand}",
                    ]
                )
                actions = [
                    {"action": "raise", "size_tag": tag, "weight": r},
                    {"action": "call", "weight": c},
                    {"action": "fold", "weight": f},
                ]
                nodes.append(
                    {
                        "node_key": node_key,
                        "street": "preflop",
                        "pot_type": "single_raised",
                        "role": role,
                        "pos": pos,
                        "texture": "na",
                        "spr": "na",
                        "facing": "na",
                        "bucket": "na",
                        "actions": actions,
                        "meta": {"facing_fallback": False, "fallback_from": []},
                    }
                )

    manifest = _load_yaml(configs_dir / "policy_manifest.yaml")
    facing_overrides, overrides_provided = _resolve_facing_overrides(classifiers, manifest)

    # Postflop helper to add bet/check nodes for a given street
    def _add_postflop(street: str, labels: list[str], include_limped: bool) -> None:
        pot_types = ["single_raised"] + (["limped"] if include_limped else [])
        for pot in pot_types:
            for role in ["na"] if pot == "limped" else ["pfr", "caller"]:
                for pos in ("ip", "oop"):
                    texture_iter = (
                        [t for t in textures if t != "na"]
                        if street in {"flop", "turn"}
                        else ["na", "dry", "semi", "wet"]
                    )
                    for texture in texture_iter:
                        # River texture may not be used; include 'na' to widen coverage
                        for spr in sprs:
                            if street == "preflop":
                                continue
                            for hand in labels:
                                bet_w, size_tag = _bet_check_mix(hand, texture, spr)
                                base_key_parts = [
                                    street,
                                    pot,
                                    role,
                                    pos,
                                    f"texture={texture}",
                                    f"spr={spr}",
                                ]
                                node_key = "|".join(
                                    [
                                        *base_key_parts,
                                        "facing=na",
                                        f"hand={hand}",
                                    ]
                                )
                                actions = [
                                    {"action": "bet", "size_tag": size_tag, "weight": bet_w},
                                    {"action": "check", "weight": 1.0 - bet_w},
                                ]
                                base_node = {
                                    "node_key": node_key,
                                    "street": street,
                                    "pot_type": pot,
                                    "role": role,
                                    "pos": pos,
                                    "texture": texture,
                                    "spr": spr,
                                    "facing": "na",
                                    "bucket": "na",
                                    "hand": hand,
                                    "actions": actions,
                                    "meta": {"facing_fallback": False, "fallback_from": []},
                                }
                                nodes.append(base_node)

                                for facing in FACING_TAGS:
                                    actions_def, is_fallback = _defence_actions(
                                        facing,
                                        facing_overrides,
                                        overrides_provided=overrides_provided,
                                    )
                                    if actions_def is None:
                                        _record_fallback(base_node, facing)
                                        continue

                                    facing_key = "|".join(
                                        [
                                            *base_key_parts,
                                            f"facing={facing}",
                                            f"hand={hand}",
                                        ]
                                    )
                                    nodes.append(
                                        {
                                            "node_key": facing_key,
                                            "street": street,
                                            "pot_type": pot,
                                            "role": role,
                                            "pos": pos,
                                            "texture": texture,
                                            "spr": spr,
                                            "facing": facing,
                                            "bucket": "na",
                                            "hand": hand,
                                            "actions": actions_def,
                                            "meta": {
                                                "facing_fallback": bool(is_fallback),
                                                "fallback_from": [],
                                            },
                                        }
                                    )

    _add_postflop("flop", fl_labels, include_limped=True)
    _add_postflop("turn", tu_labels, include_limped=False)
    _add_postflop("river", rv_labels, include_limped=False)

    meta = {
        "solver_backend": "heuristic",
        "seed": seed,
        "tree_hash": None,
        "lp_value": None,
        "policy_name": "v1_table",
        "version": "v1",
    }
    return {"meta": meta, "nodes": nodes}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build policy solution JSON from configs")
    p.add_argument(
        "--workspace", default=str(Path.cwd()), help="Workspace root containing configs/"
    )
    p.add_argument("--out", required=True, help="Output JSON path for solution")
    p.add_argument("--seed", type=int, default=123)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    workspace = Path(args.workspace).expanduser().resolve()
    solution = build_solution_from_configs(workspace, seed=int(args.seed))
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(solution, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
