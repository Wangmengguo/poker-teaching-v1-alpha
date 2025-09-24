#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_json(p: Path) -> tuple[dict, int, str]:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        ver = int(p.stat().st_mtime)
        return data, ver, "ok"
    except FileNotFoundError:
        return {}, 0, "missing"
    except Exception as e:
        return {}, 0, f"error: {e}"


def _require(cond: bool, errors: list[str], msg: str):
    if not cond:
        errors.append(msg)


def validate_profile_dir(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    summary: dict[str, Any] = {"root": str(root)}

    # 支持三种策略：loose, medium, tight
    strategies = ["loose", "medium", "tight"]
    all_versions = {}
    all_status = {}
    all_counts = {}

    for strategy in strategies:
        modes_p = root / f"table_modes_{strategy}.json"
        open_p = root / "ranges" / f"preflop_open_HU_{strategy}.json"
        vs_p = root / "ranges" / f"preflop_vs_raise_HU_{strategy}.json"

        modes, v_modes, s_modes = _read_json(modes_p)
        openj, v_open, s_open = _read_json(open_p)
        vs, v_vs, s_vs = _read_json(vs_p)

        all_versions[f"{strategy}_modes"] = v_modes
        all_versions[f"{strategy}_open"] = v_open
        all_versions[f"{strategy}_vs"] = v_vs

        all_status[f"{strategy}_modes"] = s_modes
        all_status[f"{strategy}_open"] = s_open
        all_status[f"{strategy}_vs"] = s_vs

        _require(s_modes == "ok", errors, f"missing or invalid {modes_p}")
        _require(s_open == "ok", errors, f"missing or invalid {open_p}")
        _require(s_vs == "ok", errors, f"missing or invalid {vs_p}")

        if s_modes == "ok":
            hu = modes.get("HU", {}) if isinstance(modes, dict) else {}
            _require("open_bb" in hu, errors, f"{strategy}: HU.open_bb missing")
            _require(
                "defend_threshold_ip" in hu,
                errors,
                f"{strategy}: HU.defend_threshold_ip missing",
            )
            _require(
                "defend_threshold_oop" in hu,
                errors,
                f"{strategy}: HU.defend_threshold_oop missing",
            )

        if s_open == "ok":
            sb = openj.get("SB", []) if isinstance(openj, dict) else []
            _require(isinstance(sb, list), errors, f"{strategy}: open.SB must be a list")
            all_counts[f"{strategy}_open_sb"] = len(sb)

        if s_vs == "ok":
            bbsb = vs.get("BB_vs_SB", {}) if isinstance(vs, dict) else {}
            for b in ("small", "mid", "large"):
                obj = bbsb.get(b, {})
                _require(
                    isinstance(obj.get("call", []), list),
                    errors,
                    f"{strategy}: vs.{b}.call must be list",
                )
                _require(
                    isinstance(obj.get("reraise", []), list),
                    errors,
                    f"{strategy}: vs.{b}.reraise must be list",
                )

    summary["versions"] = all_versions
    summary["status"] = all_status
    summary["counts"] = all_counts

    summary["errors"] = errors
    summary["warnings"] = warnings
    summary["ok"] = len(errors) == 0
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate SUGGEST_CONFIG_DIR profile structure")
    ap.add_argument(
        "path",
        help="Path to config dir (contains table_modes_*.json and ranges/preflop_*_*.json)",
    )
    args = ap.parse_args()
    root = Path(args.path).expanduser().resolve()
    res = validate_profile_dir(root)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
