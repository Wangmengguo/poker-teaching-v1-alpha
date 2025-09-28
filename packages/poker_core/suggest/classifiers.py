"""Shared classifiers for board textures and SPR bins."""

from __future__ import annotations

import math
import os
from collections import Counter
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

from poker_core.cards import RANK_ORDER


def _classifiers_path() -> Path:
    override = os.getenv("SUGGEST_CLASSIFIERS_FILE")
    if override:
        p = Path(override).expanduser().resolve()
        if p.exists():
            return p
    return Path(__file__).resolve().parents[3] / "configs" / "classifiers.yaml"


def _load_yaml(path: Path) -> Mapping[str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
        if isinstance(data, Mapping):
            return data
    except Exception:
        pass
    return {}


@lru_cache(maxsize=1)
def _classifiers_config() -> Mapping[str, object]:
    return _load_yaml(_classifiers_path())


def _texture_config() -> Mapping[str, object]:
    cfg = _classifiers_config().get("texture", {})
    return cfg if isinstance(cfg, Mapping) else {}


def _spr_config() -> Mapping[str, object]:
    cfg = _classifiers_config().get("spr_bins", {})
    return cfg if isinstance(cfg, Mapping) else {}


def _texture_alias_map() -> Mapping[str, str]:
    cfg = _texture_config()
    aliases: dict[str, str] = {}
    raw = cfg.get("aliases", {}) if isinstance(cfg, Mapping) else {}
    if isinstance(raw, Mapping):
        for canonical, values in raw.items():
            canon = _slug(canonical)
            aliases[canon] = canon
            if isinstance(values, Iterable):
                for v in values:
                    aliases[_slug(v)] = canon
    return aliases


def _spr_alias_map() -> Mapping[str, str]:
    cfg = _spr_config()
    aliases: dict[str, str] = {}
    bins = cfg.get("bins", []) if isinstance(cfg, Mapping) else []
    if isinstance(bins, Iterable):
        for bin_cfg in bins:
            if not isinstance(bin_cfg, Mapping):
                continue
            label = _slug(bin_cfg.get("label"))
            if not label:
                continue
            aliases[label] = label
            raw_aliases = bin_cfg.get("aliases")
            if isinstance(raw_aliases, Iterable):
                for alias in raw_aliases:
                    aliases[_slug(alias)] = label
    extra = cfg.get("aliases", {}) if isinstance(cfg, Mapping) else {}
    if isinstance(extra, Mapping):
        for label, raw_aliases in extra.items():
            canon = _slug(label)
            aliases[canon] = canon
            if isinstance(raw_aliases, Iterable):
                for alias in raw_aliases:
                    aliases[_slug(alias)] = canon
    return aliases


def _slug(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in text)


def _board_features(board: Sequence[str] | None) -> dict[str, object]:
    cards = [str(c) for c in (board or []) if c]
    if len(cards) < 3:
        return {
            "paired": False,
            "max_suit_count": 0,
            "gaps": (),
            "max_gap": None,
        }

    ranks = [card[:-1] for card in cards[:3]]
    suits = [card[-1] for card in cards[:3]]
    paired = len(set(ranks)) < len(ranks)

    suit_counter = Counter(suits)
    max_suit_count = max(suit_counter.values()) if suit_counter else 0

    values = sorted(RANK_ORDER.get(rank, 0) for rank in ranks)
    gaps: list[int] = []
    for i in range(len(values) - 1):
        gaps.append(values[i + 1] - values[i])
    max_gap = max(gaps) if gaps else None

    return {
        "paired": paired,
        "max_suit_count": max_suit_count,
        "gaps": tuple(gaps),
        "max_gap": max_gap,
    }


def classify_board_texture(board: Sequence[str] | None) -> str:
    """Return canonical board texture label using config thresholds."""

    features = _board_features(board)
    if len(tuple(board or [])) < 3:
        return _texture_alias_map().get("na", "na")

    cfg = _texture_config()
    order = cfg.get("classification_order", []) if isinstance(cfg, Mapping) else []
    default_label = _slug(cfg.get("default") if isinstance(cfg, Mapping) else "dry") or "dry"

    paired = bool(features.get("paired"))
    max_suit_count = features.get("max_suit_count")
    max_suit = int(max_suit_count) if isinstance(max_suit_count, int) else 0
    max_gap_val = features.get("max_gap")
    max_gap_int: int | None = int(max_gap_val) if isinstance(max_gap_val, int) else None

    for rule in order if isinstance(order, Iterable) else []:
        if not isinstance(rule, Mapping):
            continue
        label = _slug(rule.get("label"))
        if not label:
            continue
        conditions = rule.get("conditions") if isinstance(rule, Mapping) else {}
        if not isinstance(conditions, Mapping):
            conditions = {}
        if _match_texture_conditions(conditions, paired, max_suit, max_gap_int):
            return label

    return default_label


def _match_texture_conditions(
    conditions: Mapping[str, object], paired: bool, max_suit: int, max_gap_val: int | None
) -> bool:
    for key, expected in conditions.items():
        if key == "paired":
            if bool(expected) != paired:
                return False
        elif key == "suits_at_least":
            threshold_int = 0
            if isinstance(expected, int):
                threshold_int = expected
            elif isinstance(expected, (str, float)):
                try:
                    threshold_int = int(expected)
                except Exception:
                    threshold_int = 0
            if max_suit < threshold_int:
                return False
        elif key == "max_gap":
            if max_gap_val is None:
                return False
            threshold_float = math.inf
            if isinstance(expected, int):
                threshold_float = float(expected)
            elif isinstance(expected, (str, float)):
                try:
                    threshold_float = float(expected)
                except Exception:
                    threshold_float = math.inf
            if max_gap_val > threshold_float:
                return False
        else:
            return False
    return True


def classify_spr_bin(spr_value: float | None, alias: str | None) -> str:
    """Return canonical SPR bin label using numeric value or legacy alias."""

    alias_map = _spr_alias_map()
    alias_key = _slug(alias)
    if alias_key and alias_key in alias_map and alias_map[alias_key]:
        return alias_map[alias_key]

    if spr_value is None:
        return alias_map.get("na", "na")
    try:
        value = float(spr_value)
    except Exception:
        return alias_map.get("na", "na")
    if not math.isfinite(value):
        return alias_map.get("na", "na")

    cfg = _spr_config()
    bins_raw = cfg.get("bins", []) if isinstance(cfg, Mapping) else []
    last_label = "spr10"
    if isinstance(bins_raw, Sequence) and bins_raw:
        last = bins_raw[-1]
        if isinstance(last, Mapping):
            last_label = _slug(last.get("label")) or last_label
    bins_iter = bins_raw if isinstance(bins_raw, Iterable) else []

    for bin_cfg in bins_iter:
        if not isinstance(bin_cfg, Mapping):
            continue
        label = _slug(bin_cfg.get("label"))
        if not label:
            continue
        upper = bin_cfg.get("upper")
        if upper is None:
            return label
        try:
            upper_val = float(upper)
        except Exception:
            continue
        if value < upper_val or math.isclose(value, upper_val, rel_tol=1e-9, abs_tol=1e-9):
            if math.isclose(value, upper_val, rel_tol=1e-9, abs_tol=1e-9):
                # Boundary values fall to the higher bin; continue unless last bin.
                continue
            return label
    return last_label or "spr10"


def canonical_texture_from_alias(value: object) -> str:
    return _texture_alias_map().get(_slug(value), "na")


def canonical_spr_from_alias(value: object) -> str:
    return _spr_alias_map().get(_slug(value), "na")


__all__ = [
    "classify_board_texture",
    "classify_spr_bin",
    "canonical_texture_from_alias",
    "canonical_spr_from_alias",
]
