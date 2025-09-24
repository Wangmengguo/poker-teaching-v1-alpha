#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def _resolve_repo_root() -> Path:
    here = Path(__file__).resolve()
    return here.parent.parent


def _ensure_path() -> None:
    root = _resolve_repo_root()
    pkg = root / "packages"
    if str(pkg) not in sys.path:
        sys.path.insert(0, str(pkg))


_ensure_path()

from poker_core.suggest.flop_rules import load_flop_rules  # type: ignore  # noqa: E402


def _validate_size_tag(obj: Any, path: str, errors: list[str]) -> None:
    if not isinstance(obj, dict):
        return
    if "action" in obj:
        st = obj.get("size_tag")
        if obj.get("action") in ("bet", "raise"):
            if st not in ("third", "half", "two_third", "pot", None):
                errors.append(f"invalid size_tag at {path}: {st}")


def _validate_facing(
    obj: Any, path: str, errors: list[str], warnings: list[str]
) -> None:
    if not isinstance(obj, dict):
        return
    facing = obj.get("facing")
    if facing is None:
        return
    if not isinstance(facing, dict):
        errors.append(f"facing must be object at {path}")
        return
    allowed = {"third", "half", "two_third_plus"}
    for k, v in facing.items():
        if k not in allowed:
            warnings.append(f"unknown facing key at {path}: {k}")
            continue
        if not isinstance(v, dict) or v.get("action") not in ("raise", "call", "fold"):
            errors.append(f"invalid facing leaf at {path}.{k}")
            continue
        if v.get("action") == "raise":
            st = v.get("size_tag")
            if st not in ("third", "half", "two_third", "pot"):
                errors.append(f"invalid facing size_tag at {path}.{k}: {st}")


def validate_rules(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    warnings: list[str] = []
    if "single_raised" not in data:
        errors.append("missing key: single_raised")
        return errors
    node = data["single_raised"]
    if "role" not in node:
        errors.append("missing key: role under single_raised")
        return errors
    for role in ("pfr", "caller"):
        rnode = (node["role"] or {}).get(role)
        if not isinstance(rnode, dict):
            errors.append(f"missing role node: {role}")
            continue
        for pos in ("ip", "oop"):
            pnode = rnode.get(pos) or {}
            if not isinstance(pnode, dict):
                errors.append(f"missing ip/oop node: {role}.{pos}")
                continue
            # texture defaults
            has_any = any(k in pnode for k in ("dry", "semi", "wet", "defaults"))
            if not has_any:
                errors.append(f"no texture keys under {role}.{pos}")
            for tex in ("dry", "semi", "wet"):
                tnode = pnode.get(tex) or {}
                if not isinstance(tnode, dict):
                    continue
                if "defaults" not in tnode:
                    errors.append(f"missing defaults under {role}.{pos}.{tex}")
                for spr in ("le3", "3to6", "ge6"):
                    snode = tnode.get(spr) or {}
                    if not isinstance(snode, dict):
                        continue
                    # ensure six-class keys exist (may be mapped to check defaults)
                    classes = {
                        "value_two_pair_plus",
                        "overpair_or_top_pair_strong",
                        "top_pair_weak_or_second_pair",
                        "middle_pair_or_third_pair_minus",
                        "strong_draw",
                        "weak_draw_or_air",
                    }
                    missing = [c for c in classes if c not in snode]
                    if missing:
                        errors.append(
                            f"missing classes at {role}.{pos}.{tex}.{spr}: {','.join(missing)}"
                        )
                    # validate leaf size_tag domains
                    for k, v in snode.items():
                        _validate_size_tag(v, f"{role}.{pos}.{tex}.{spr}.{k}", errors)
                        if k == "value_two_pair_plus":
                            _validate_facing(
                                v, f"{role}.{pos}.{tex}.{spr}.{k}", errors, warnings
                            )
    # print warnings as JSON once
    if warnings:
        print(
            json.dumps(
                {"warnings": warnings[:16], "warning_count": len(warnings)},
                ensure_ascii=False,
                indent=2,
            )
        )
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Validate flop_rules_HU_{strategy}.json with optional monotonic smoke checks"
    )
    default_strategy = os.getenv("CHECK_ONLY_STRATEGY", "medium")
    ap.add_argument("--strategy", default=default_strategy, help="loose|medium|tight")
    ap.add_argument(
        "--all",
        action="store_true",
        help="Validate all strategies and run monotonic checks (smoke)",
    )
    ap.add_argument(
        "--mono-hard",
        action="store_true",
        help="Fail on monotonic mismatches (default: smoke only)",
    )
    args = ap.parse_args()

    def _emit(strategy: str, validate: bool = True) -> tuple[bool, dict]:
        data, ver = load_flop_rules(strategy)
        errs = validate_rules(data) if validate else []
        sample = {
            "pfr_ip_dry_default": data.get("single_raised", {})
            .get("role", {})
            .get("pfr", {})
            .get("ip", {})
            .get("dry", {})
            .get("defaults"),
            "caller_ip_wet_le3_value": data.get("single_raised", {})
            .get("role", {})
            .get("caller", {})
            .get("ip", {})
            .get("wet", {})
            .get("le3", {})
            .get("value_two_pair_plus"),
        }
        out = {
            "strategy": strategy,
            "version": ver,
            "errors": errs,
            "ok": not errs,
            "sample": sample,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return (not errs), data

    ok, data_one = _emit(args.strategy, validate=True)
    exit_code = 0 if ok else 1

    if args.all:
        # Load all three for monotonic smoke (loose ⊇ medium ⊇ tight)
        # Medium: hard validation; Loose/Tight: smoke (no schema gate)
        ok_l, data_l = _emit("loose", validate=False)
        ok_m, data_m = _emit("medium", validate=True)
        ok_t, data_t = _emit("tight", validate=False)

        def _get_action(
            d: dict[str, Any], role: str, pos: str, tex: str, spr: str, cls: str
        ) -> str | None:
            try:
                node = (
                    d.get("single_raised", {})
                    .get("role", {})
                    .get(role, {})
                    .get(pos, {})
                )
                # texture level
                tn = node.get(tex) or {}
                # fallback defaults at texture when needed
                if spr in tn:
                    ln = tn.get(spr) or {}
                    leaf = ln.get(cls)
                    if isinstance(leaf, dict) and "action" in leaf:
                        return str(leaf.get("action"))
                # texture defaults
                leaf = tn.get("defaults") or {}
                if isinstance(leaf, dict) and "action" in leaf:
                    return str(leaf.get("action"))
                return None
            except Exception:
                return None

        roles = ("pfr", "caller")
        poses = ("ip", "oop")
        texs = ("dry", "semi", "wet")
        sprs = ("le3", "3to6", "ge6")
        classes = (
            "value_two_pair_plus",
            "overpair_or_top_pair_strong",
            "top_pair_weak_or_second_pair",
            "middle_pair_or_third_pair_minus",
            "strong_draw",
            "weak_draw_or_air",
        )
        rank = {None: -1, "check": 0, "bet": 1, "raise": 2}
        mismatches: list[dict[str, Any]] = []
        missing_pairs = {"loose_vs_medium": 0, "medium_vs_tight": 0}
        for r in roles:
            for p in poses:
                for t in texs:
                    for s in sprs:
                        for c in classes:
                            al = _get_action(data_l, r, p, t, s, c)
                            am = _get_action(data_m, r, p, t, s, c)
                            at = _get_action(data_t, r, p, t, s, c)
                            if al is None and am is None and at is None:
                                continue
                            # Only compare pairs when both sides present; otherwise count as missing (smoke)
                            # loose vs medium
                            if am is not None and al is not None:
                                if rank[al] < rank[am]:
                                    mismatches.append(
                                        {
                                            "pair": "loose>=medium",
                                            "path": f"{r}.{p}.{t}.{s}.{c}",
                                            "loose": al,
                                            "medium": am,
                                        }
                                    )
                            else:
                                missing_pairs["loose_vs_medium"] += 1
                            # medium vs tight
                            if am is not None and at is not None:
                                if rank[am] < rank[at]:
                                    mismatches.append(
                                        {
                                            "pair": "medium>=tight",
                                            "path": f"{r}.{p}.{t}.{s}.{c}",
                                            "medium": am,
                                            "tight": at,
                                        }
                                    )
                            else:
                                missing_pairs["medium_vs_tight"] += 1

        mono_summary = {
            "monotonic_mismatches": len(mismatches),
            "missing_pairs": missing_pairs,
            "examples": mismatches[:8],
        }
        print(json.dumps(mono_summary, ensure_ascii=False, indent=2))
        if mismatches and (args.mono_hard or os.getenv("MONO_HARD") == "1"):
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
