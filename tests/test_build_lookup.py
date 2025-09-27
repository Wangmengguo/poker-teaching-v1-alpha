import json

import numpy as np

from tools.build_lookup import build_lookup_tables

EXPECTED_SPR_BINS = ["spr2", "spr4", "spr6", "spr8", "spr10"]


def test_build_lookup_uses_configured_spr_bins(tmp_path):
    out_dir = tmp_path / "lookup"

    artifacts = build_lookup_tables("hs", ["flop"], out_dir, seed=123)

    assert len(artifacts) == 1
    lookup = np.load(artifacts[0])

    spr_bins = lookup["spr_bins"].tolist()
    assert spr_bins == EXPECTED_SPR_BINS

    meta = json.loads(lookup["meta"].item())
    assert meta["spr_bins"] == EXPECTED_SPR_BINS
