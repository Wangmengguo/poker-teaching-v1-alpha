"""Runtime lookup helpers for precomputed hand strength and pot odds tables."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

LOOKUP_ROOT = Path(
    os.getenv(
        "POKER_LOOKUP_ROOT",
        Path(__file__).resolve().parents[3] / "artifacts" / "lookup",
    )
)
OUTS_CONFIG_PATH = Path(__file__).resolve().parent / "outs_weights.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text()
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
    except Exception:
        data = json.loads(text)
    if not isinstance(data, dict):  # pragma: no cover
        raise ValueError("outs weights config must be a mapping")
    return data


@lru_cache(maxsize=1)
def _outs_config() -> dict[str, Any]:
    return _load_yaml(OUTS_CONFIG_PATH)


def outs_to_river(outs: int | None = None, quality: str | None = None) -> float:
    cfg = _outs_config()
    defaults = cfg.get("defaults", {})
    outs_val = outs if outs is not None else int(defaults.get("outs", 8))
    base_prob = float(defaults.get("per_out", 0.021))
    weight = cfg.get("quality_weights", {}).get(quality or "standard", 1.0)
    estimate = outs_val * base_prob * weight
    return float(min(max(estimate, 0.0), 0.95))


class LookupTable:
    def __init__(self, kind: str):
        self.kind = kind

    @lru_cache(maxsize=16)
    def _load(self, street: str) -> dict[str, Any]:
        path = LOOKUP_ROOT / f"{self.kind}_{street}.npz"
        if not path.exists():
            raise FileNotFoundError(f"lookup file missing: {path}")
        payload = np.load(path, allow_pickle=True)
        textures = [str(x) for x in payload["texture_tags"]]
        spr_bins = [str(x) for x in payload["spr_bins"]]
        values = payload["values"].astype(float)
        meta = json.loads(str(payload["meta"].item()))
        return {
            "values": values,
            "textures": textures,
            "spr_bins": spr_bins,
            "meta": meta,
        }

    def get(
        self,
        street: str,
        texture: str,
        spr_bin: str,
        bucket: int,
        *,
        quality: str | None = None,
    ) -> float:
        street = (street or "").lower()
        try:
            data = self._load(street)
        except FileNotFoundError:
            return outs_to_river(quality=quality)

        textures = data["textures"]
        spr_bins = data["spr_bins"]
        try:
            t_idx = textures.index(texture)
            s_idx = spr_bins.index(spr_bin)
            if bucket < 0 or bucket >= data["values"].shape[2]:
                raise IndexError
            value = float(data["values"][t_idx, s_idx, bucket])
            return value
        except (ValueError, IndexError):
            return outs_to_river(quality=quality)


hs_lookup = LookupTable("hs")
pot_lookup = LookupTable("pot")


__all__ = ["hs_lookup", "pot_lookup", "outs_to_river"]
