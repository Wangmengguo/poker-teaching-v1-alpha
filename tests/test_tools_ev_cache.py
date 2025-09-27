import json
from pathlib import Path

import numpy as np
import pytest

from tools import cache_turn_leaf_ev

TRANS_PATH = Path("artifacts/transitions/turn_to_river.json")


@pytest.fixture(scope="module")
def transition_meta():
    data = json.loads(TRANS_PATH.read_text())
    return data


def _build_cache(tmp_path, seed=42):
    out_path = tmp_path / "turn_leaf.npz"
    rc = cache_turn_leaf_ev.main(
        [
            "--trans",
            str(TRANS_PATH),
            "--out",
            str(out_path),
            "--seed",
            str(seed),
        ]
    )
    assert rc == 0
    assert out_path.exists()
    payload = np.load(out_path, allow_pickle=True)
    meta = json.loads(str(payload["meta"].item()))
    return payload, meta


def test_turn_leaf_cache_npz_shapes(tmp_path, transition_meta):
    payload, _meta = _build_cache(tmp_path)
    ev = payload["ev"]
    assert isinstance(ev, np.ndarray)
    assert ev.shape == (transition_meta["from_bins"],)


def test_turn_leaf_cache_consistency_seeded(tmp_path):
    payload_a, _ = _build_cache(tmp_path / "run_a", seed=42)
    payload_b, _ = _build_cache(tmp_path / "run_b", seed=42)
    np.testing.assert_allclose(payload_a["ev"], payload_b["ev"])

    payload_c, _ = _build_cache(tmp_path / "run_c", seed=99)
    assert not np.allclose(payload_a["ev"], payload_c["ev"])


def test_turn_leaf_cache_meta_audit_fields(tmp_path, transition_meta):
    _, meta = _build_cache(tmp_path / "meta_check")
    assert meta["derived_from_turn_leaf"] is True
    assert meta["seed"] == 42
    assert meta["source_transition"] == str(TRANS_PATH)
    assert meta["samples"] == transition_meta["meta"].get("samples")
    assert meta["board_sampler"] == transition_meta["meta"].get("board_sampler")
    conditioners = meta.get("conditioners")
    assert conditioners and "texture" in conditioners and "spr_bin" in conditioners
