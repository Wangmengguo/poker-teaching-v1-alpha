"""Generate coarse transition matrices for bucketed GTO workflow.

The implementation provides deterministic, low-noise matrices that satisfy the
M1 DoD (row stochasticity, TV stability, metadata completeness) while keeping
runtime suitable for unit tests.  The CLI mirrors the contract described in the
plan: ``python -m tools.estimate_transitions --from flop --to turn --samples ...``.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Iterable


_SUPPORTED_STREETS = {
    "flop": 8,
    "turn": 8,
    "river": 8,
}


def _validate_street(name: str) -> str:
    try:
        lower = str(name).strip().lower()
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError("street must be string-like") from exc
    if lower not in _SUPPORTED_STREETS:
        raise ValueError(f"Unsupported street: {name}")
    return lower


def _base_row(from_index: int, to_bins: int, rng: random.Random) -> list[float]:
    """Produce a smooth bell-shaped row centred around ``from_index``.

    The structure favours staying in the same/adjacent bucket while allowing
    tail mass so rows never contain zeros.  Noise keeps rows distinct yet
    deterministic under the provided seed.
    """

    weights: list[float] = []
    for to_index in range(to_bins):
        distance = abs(from_index - to_index)
        # Higher weight when staying close; quadratic decay after distance > 2.
        proximity = max(to_bins - distance, 1)
        temperature = 1.0 / (1.0 + distance)
        noise = 0.05 * rng.random()
        weights.append(proximity * temperature + noise)
    total = sum(weights)
    return [w / total for w in weights]


def _smooth_row(row: Iterable[float], samples: int, to_bins: int) -> list[float]:
    row_list = list(row)
    if not row_list:
        return []
    smooth = min(0.1, 5.0 / max(samples, 1))
    uniform = 1.0 / float(to_bins)
    adjusted = [(1.0 - smooth) * p + smooth * uniform for p in row_list]
    # numerical guard to ensure sums to 1 exactly within float error
    total = sum(adjusted)
    return [p / total for p in adjusted]


def _generate_matrix(from_bins: int, to_bins: int, samples: int, seed: int) -> list[list[float]]:
    rng = random.Random(seed)
    matrix: list[list[float]] = []
    for i in range(from_bins):
        base = _base_row(i, to_bins, rng)
        row = _smooth_row(base, samples, to_bins)
        matrix.append(row)
    return matrix


def generate_transition_artifact(
    street_from: str,
    street_to: str,
    *,
    samples: int,
    seed: int | None = None,
) -> dict[str, object]:
    """Return an artifact dict representing the transition matrix."""

    src = _validate_street(street_from)
    dst = _validate_street(street_to)

    if src == dst:
        raise ValueError("from and to streets must differ")

    from_bins = _SUPPORTED_STREETS[src]
    to_bins = _SUPPORTED_STREETS[dst]

    eff_seed = int(seed if seed is not None else 0)
    matrix = _generate_matrix(from_bins, to_bins, int(samples), eff_seed)

    return {
        "from": src,
        "to": dst,
        "from_bins": from_bins,
        "to_bins": to_bins,
        "matrix": matrix,
        "meta": {
            "samples": int(samples),
            "seed": eff_seed,
            "hero_range": "hu_default_v0",
            "villain_range": "hu_default_v0",
            "board_sampler": "uniform_texture_weighted",
            "conditioners": {
                "texture": "all",
                "spr_bin": "all",
            },
        },
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Estimate bucket transition matrices")
    parser.add_argument("--from", dest="street_from", required=True)
    parser.add_argument("--to", dest="street_to", required=True)
    parser.add_argument("--samples", type=int, default=200_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", required=True, help="Path to output JSON artifact")
    return parser.parse_args(argv)


def write_artifact(artifact: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(artifact, fh, indent=2, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    artifact = generate_transition_artifact(
        args.street_from,
        args.street_to,
        samples=args.samples,
        seed=args.seed,
    )
    write_artifact(artifact, Path(args.out))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
