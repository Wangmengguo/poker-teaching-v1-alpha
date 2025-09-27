import json
from pathlib import Path

import numpy as np

from tools import build_lookup
from packages.poker_core.suggest import lookup

LOOKUP_DIR = Path("artifacts/lookup")


def _ensure_tables():
    build_lookup.main(
        [
            "--type",
            "hs",
            "--streets",
            "preflop,flop,turn",
            "--out",
            str(LOOKUP_DIR),
        ]
    )
    build_lookup.main(
        [
            "--type",
            "pot",
            "--streets",
            "flop,turn",
            "--out",
            str(LOOKUP_DIR),
        ]
    )


def _load_npz(path: Path):
    payload = np.load(path, allow_pickle=True)
    meta = json.loads(str(payload["meta"].item()))
    return payload, meta


def test_lookup_files_exist_and_shapes(tmp_path):
    _ensure_tables()
    hs_flop = LOOKUP_DIR / "hs_flop.npz"
    pot_turn = LOOKUP_DIR / "pot_turn.npz"
    assert hs_flop.exists()
    assert pot_turn.exists()

    payload, meta = _load_npz(hs_flop)
    values = payload["values"]
    assert values.shape == (3, 3, 8)
    assert meta["kind"] == "hs"

    payload_pot, meta_pot = _load_npz(pot_turn)
    assert payload_pot["values"].shape == (3, 3, 8)
    assert meta_pot["kind"] == "pot"


def test_lookup_api_present_and_fallback():
    _ensure_tables()
    value = lookup.hs_lookup.get("flop", "dry", "low", 2)
    assert 0.0 <= value <= 1.0

    fallback = lookup.outs_to_river()
    missing = lookup.hs_lookup.get("flop", "unknown_texture", "low", 2)
    assert abs(missing - fallback) < 1e-6
