"""Lookup table builder for hand-strength and pot odds approximations."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Iterable

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
CLASSIFIERS_PATH = REPO_ROOT / "configs" / "classifiers.yaml"


def _load_yaml(path: Path) -> dict:
    text = path.read_text()
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
    except Exception:
        data = json.loads(text)
    if not isinstance(data, dict):  # pragma: no cover - guard
        raise ValueError("classifiers config must be a mapping")
    return data


def _bucket_count(street: str) -> int:
    street = street.lower()
    if street == "preflop":
        return 6
    return 8


def _generate_values(kind: str, street: str, textures: Iterable[str], spr_bins: Iterable[str], buckets: int, seed: int) -> tuple[np.ndarray, dict]:
    textures = list(textures)
    spr_bins = list(spr_bins)
    rng = random.Random(seed)
    values = np.zeros((len(textures), len(spr_bins), buckets), dtype=np.float32)
    for t_idx, _ in enumerate(textures):
        for s_idx, _ in enumerate(spr_bins):
            for b in range(buckets):
                base = 0.18 + 0.05 * t_idx + 0.04 * s_idx + 0.03 * b
                jitter = (rng.random() - 0.5) * 0.04
                if kind == "pot":
                    value = 1.0 + 0.15 * s_idx + 0.08 * b + jitter
                    value = float(max(0.5, value))
                else:
                    value = float(min(0.95, max(0.05, base + jitter)))
                values[t_idx, s_idx, b] = value
    meta = {
        "kind": kind,
        "street": street,
        "texture_tags": textures,
        "spr_bins": spr_bins,
    }
    return values, meta


def build_lookup_tables(kind: str, streets: list[str], out_dir: Path, seed: int = 42) -> list[Path]:
    classifiers = _load_yaml(CLASSIFIERS_PATH)
    textures = classifiers.get("texture_tags") or ["dry", "semi", "wet"]
    spr_bins = classifiers.get("spr_bins", {}).get("labels") or ["low", "mid", "high"]

    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[Path] = []
    for idx, street in enumerate(streets):
        buckets = _bucket_count(street)
        values, meta = _generate_values(kind, street, textures, spr_bins, buckets, seed + idx * 13)
        payload = {
            "values": values,
            "texture_tags": np.array(textures),
            "spr_bins": np.array(spr_bins),
            "meta": np.array(json.dumps(meta)),
            "buckets": np.arange(buckets, dtype=np.int16),
        }
        out_path = out_dir / f"{kind}_{street}.npz"
        np.savez(out_path, **payload)
        artifacts.append(out_path)
    return artifacts


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build lookup tables")
    parser.add_argument("--type", choices=["hs", "pot"], required=True)
    parser.add_argument("--streets", default="preflop,flop,turn", help="Comma separated streets")
    parser.add_argument("--out", required=True, help="Output directory for lookup NPZ files")
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    streets = [s.strip().lower() for s in args.streets.split(",") if s.strip()]
    build_lookup_tables(args.type, streets, Path(args.out), seed=args.seed)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
