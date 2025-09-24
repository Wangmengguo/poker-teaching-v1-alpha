from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from .config_loader import load_json_cached


def _config_path_for_strategy(strategy: str) -> str:
    s = (strategy or "medium").lower()
    if s not in ("loose", "medium", "tight"):
        s = "medium"
    return f"postflop/flop_rules_HU_{s}.json"


@lru_cache(maxsize=8)
def load_flop_rules(strategy: str) -> tuple[dict[str, Any], int]:
    rel = _config_path_for_strategy(strategy)
    data, ver = load_json_cached(rel)
    _warn_missing_defaults_once(data, ver, strategy)
    return (data or {}), int(ver or 0)


def get_flop_rules() -> tuple[dict[str, Any], int]:
    import os

    s = os.getenv("SUGGEST_STRATEGY", "medium").lower()
    return load_flop_rules(s)


# ---- Best-effort integrity hints (non-gating) ----
_WARNED_VERSIONS: set[tuple[str, int]] = set()


def _warn_missing_defaults_once(data: dict[str, Any], ver: int, strategy: str) -> None:
    key = (str(strategy), int(ver or 0))
    if key in _WARNED_VERSIONS:
        return
    try:
        log = logging.getLogger(__name__)
        pot_types = [
            k
            for k in (data or {}).keys()
            if k in ("single_raised", "limped", "threebet")
        ]
        missing: list[str] = []
        for pt in pot_types:
            role_node = (data or {}).get(pt, {}).get("role", {}) or {}
            for role in role_node.keys():
                for pos in ("ip", "oop"):
                    tex = (role_node.get(role, {}) or {}).get(pos, {}) or {}
                    for tname in ("dry", "semi", "wet"):
                        tnode = tex.get(tname)
                        if isinstance(tnode, dict) and "defaults" not in tnode:
                            missing.append(f"{pt}.role.{role}.{pos}.{tname}")
        if missing:
            log.warning(
                "flop_rules_missing_defaults",
                extra={
                    "strategy": strategy,
                    "version": int(ver or 0),
                    "missing_blocks": missing[:12],
                    "missing_count": len(missing),
                },
            )
    except Exception:
        pass
    _WARNED_VERSIONS.add(key)


__all__ = ["get_flop_rules", "load_flop_rules"]
