from __future__ import annotations

from functools import lru_cache
from typing import Any

from .config_loader import load_json_cached


def _config_path(strategy: str, street: str) -> str:
    s = (strategy or "medium").lower()
    if s not in ("loose", "medium", "tight"):
        s = "medium"
    if street == "turn":
        return f"postflop/turn_rules_HU_{s}.json"
    return f"postflop/river_rules_HU_{s}.json"


@lru_cache(maxsize=8)
def _load_rules(strategy: str, street: str) -> tuple[dict[str, Any], int]:
    rel = _config_path(strategy, street)
    data, ver = load_json_cached(rel)
    return (data or {}), int(ver or 0)


def get_turn_rules() -> tuple[dict[str, Any], int]:
    import os

    s = os.getenv("SUGGEST_STRATEGY", "medium").lower()
    return _load_rules(s, "turn")


def get_river_rules() -> tuple[dict[str, Any], int]:
    import os

    s = os.getenv("SUGGEST_STRATEGY", "medium").lower()
    return _load_rules(s, "river")


__all__ = ["get_turn_rules", "get_river_rules"]
