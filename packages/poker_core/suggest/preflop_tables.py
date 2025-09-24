from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from poker_core.cards import RANK_ORDER, parse_card

from .config_loader import load_json_cached


def _profile_root() -> str:
    # Use env dir; else return package builtin config path marker
    d = os.getenv("SUGGEST_CONFIG_DIR")
    if d:
        return d
    # builtin marker for debug display
    return "builtin"


def combo_from_hole(hole: list[str]) -> str | None:
    """Convert two hole cards to 169-grid combo label: 'AKs'|'KQo'|'TT'.

    - Accepts len==2 strings like 'Ah','Kd'.
    - Order-insensitive; use higher rank first.
    - Pair: 'TT'. Suitedness: 's'|'o'.
    - Returns None for invalid input.
    """
    try:
        if not hole or len(hole) != 2:
            return None
        r1, s1 = parse_card(str(hole[0]).strip())
        r2, s2 = parse_card(str(hole[1]).strip())
        v1, v2 = RANK_ORDER.get(r1), RANK_ORDER.get(r2)
        if v1 is None or v2 is None:
            return None
        if r1 == r2:
            return f"{r1}{r2}"
        # high-first ordering
        if v1 < v2:
            r1, r2, s1, s2 = r2, r1, s2, s1
        suited = s1 == s2
        return f"{r1}{r2}{'s' if suited else 'o'}"
    except Exception:
        return None


def bucket_facing_size(to_call_bb: float) -> str:
    """Classify open size bucket by to_call_bb (BB 已投 1bb):
    open_to_bb = to_call_bb + 1 → small ≤2.5 | mid ≤4 | large >4.
    """
    open_to = float(to_call_bb) + 1.0
    if open_to <= 2.5:
        return "small"
    if open_to <= 4.0:
        return "mid"
    return "large"


def _config_paths() -> tuple[str, str, str]:
    base = "ranges"

    # 支持策略选择：loose, medium, tight
    strategy = os.getenv("SUGGEST_STRATEGY", "medium").lower()
    if strategy not in ["loose", "medium", "tight"]:
        strategy = "medium"  # 默认使用medium策略

    modes_rel = f"table_modes_{strategy}.json"
    open_rel = f"{base}/preflop_open_HU_{strategy}.json"
    vs_rel = f"{base}/preflop_vs_raise_HU_{strategy}.json"
    return open_rel, vs_rel, modes_rel


@lru_cache(maxsize=16)
def _load_open(rel_path: str) -> tuple[dict[str, set[str]], int]:
    data, ver = load_json_cached(rel_path)
    out: dict[str, set[str]] = {"SB": set(), "BB": set()}
    try:
        for pos in ("SB", "BB"):
            lst = data.get(pos, []) or []
            out[pos] = set(str(x).strip() for x in lst if x)
    except Exception:
        pass
    return out, int(ver or 0)


@lru_cache(maxsize=16)
def _load_vs(rel_path: str) -> tuple[dict[str, dict[str, dict[str, set[str]]]], int]:
    data, ver = load_json_cached(rel_path)
    # Structure examples:
    #   "BB_vs_SB": {"small": {"call": [...], "reraise": [...]}, ...}
    #   "SB_vs_BB_3bet": {"small": {"fourbet": [...], "call": [...]}, ...}
    out: dict[str, dict[str, dict[str, set[str]]]] = {}
    try:
        for k, v in (data or {}).items():
            out[k] = {}
            for bkt, obj in (v or {}).items():
                # normalize keys; accept reraise as alias of fourbet for SB_vs_BB_3bet
                call_set = set((obj or {}).get("call", []) or [])
                reraise_set = set((obj or {}).get("reraise", []) or [])
                fourbet_set = set((obj or {}).get("fourbet", []) or [])
                merged: dict[str, set[str]] = {
                    "call": call_set,
                    "reraise": reraise_set,
                }
                if fourbet_set:
                    merged["fourbet"] = fourbet_set
                out[k][bkt] = merged
    except Exception:
        pass
    return out, int(ver or 0)


@lru_cache(maxsize=16)
def _load_modes(rel_path: str) -> tuple[dict[str, Any], int]:
    data, ver = load_json_cached(rel_path)
    return (data or {}), int(ver or 0)


def get_open_table() -> tuple[dict[str, set[str]], int]:
    open_rel, _, _ = _config_paths()
    return _load_open(open_rel)


def get_vs_table() -> tuple[dict[str, dict[str, dict[str, set[str]]]], int]:
    _, vs_rel, _ = _config_paths()
    return _load_vs(vs_rel)


def get_modes() -> tuple[dict[str, Any], int]:
    _, _, modes_rel = _config_paths()
    return _load_modes(modes_rel)


def config_profile_name() -> str:
    d = os.getenv("SUGGEST_CONFIG_DIR")
    if d:
        profile_name = os.path.basename(os.path.normpath(d)) or "external"
    else:
        profile_name = "builtin"

    # 添加策略信息
    strategy = os.getenv("SUGGEST_STRATEGY", "medium").lower()
    if strategy != "medium":
        profile_name = f"{profile_name}({strategy})"

    return profile_name


def config_strategy_name() -> str:
    """Return the selected strategy name (loose|medium|tight)."""
    s = os.getenv("SUGGEST_STRATEGY", "medium").lower()
    return s if s in ("loose", "medium", "tight") else "medium"
