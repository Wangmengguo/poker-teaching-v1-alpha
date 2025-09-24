"""Centralised configuration/context snapshot for suggest policies."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .preflop_tables import (
    config_profile_name,
    config_strategy_name,
    get_modes,
    get_open_table,
    get_vs_table,
)


@dataclass(frozen=True)
class SuggestFlags:
    enable_flop_value_raise: bool


@dataclass(frozen=True)
class SuggestProfile:
    strategy_name: str
    config_profile: str


@dataclass(frozen=True)
class SuggestContext:
    modes: Mapping[str, Any]
    open_table: Mapping[str, Any]
    vs_table: Mapping[str, Any]
    versions: Mapping[str, int]
    flags: SuggestFlags
    profile: SuggestProfile

    @classmethod
    def build(cls) -> SuggestContext:
        open_table, ver_open = get_open_table()
        vs_table, ver_vs = get_vs_table()
        modes, ver_modes = get_modes()

        flags = SuggestFlags(
            enable_flop_value_raise=_env_flag("SUGGEST_FLOP_VALUE_RAISE", default=True),
        )

        profile = SuggestProfile(
            strategy_name=config_strategy_name(),
            config_profile=config_profile_name(),
        )

        versions = {
            "open": int(ver_open or 0),
            "vs": int(ver_vs or 0),
            "modes": int(ver_modes or 0),
        }

        return cls(
            modes=modes,
            open_table=open_table,
            vs_table=vs_table,
            versions=versions,
            flags=flags,
            profile=profile,
        )


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    value = raw.strip()
    if value == "":
        return bool(default)
    if default:
        # default True: only "0" disables
        return value != "0"
    # default False: only "1" enables
    return value == "1"


__all__ = ["SuggestContext", "SuggestFlags", "SuggestProfile"]
