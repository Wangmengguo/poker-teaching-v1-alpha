import json

import pytest

from tools import estimate_transitions


@pytest.mark.parametrize(
    "street_from,street_to",
    [("flop", "turn"), ("turn", "river")],
)
def test_transitions_row_stochastic(street_from, street_to):
    artifact = estimate_transitions.generate_transition_artifact(
        street_from,
        street_to,
        samples=5000,
        seed=123,
    )
    matrix = artifact["matrix"]
    for row in matrix:
        assert row, "each row should contain probabilities"
        row_sum = sum(row)
        assert pytest.approx(1.0, abs=1e-6) == row_sum


def test_transitions_tv_distance_small_when_sample_increases():
    small = estimate_transitions.generate_transition_artifact(
        "flop",
        "turn",
        samples=10_000,
        seed=42,
    )
    large = estimate_transitions.generate_transition_artifact(
        "flop",
        "turn",
        samples=20_000,
        seed=42,
    )
    matrix_small = small["matrix"]
    matrix_large = large["matrix"]

    def _row_tv_distance(row_a, row_b):
        return sum(abs(a - b) for a, b in zip(row_a, row_b)) / 2.0

    max_tv = max(
        _row_tv_distance(row_a, row_b)
        for row_a, row_b in zip(matrix_small, matrix_large)
    )
    assert max_tv < 0.05


@pytest.mark.parametrize("street_from,street_to", [("flop", "turn"), ("turn", "river")])
def test_transitions_meta_semantics_present(street_from, street_to, tmp_path):
    out_path = tmp_path / f"{street_from}_to_{street_to}.json"
    rc = estimate_transitions.main(
        [
            "--from",
            street_from,
            "--to",
            street_to,
            "--samples",
            "1000",
            "--out",
            str(out_path),
            "--seed",
            "7",
        ]
    )
    assert rc == 0
    assert out_path.exists()
    artifact = json.loads(out_path.read_text())
    meta = artifact.get("meta", {})
    assert meta.get("samples") == 1000
    assert meta.get("hero_range")
    assert meta.get("villain_range")
    assert meta.get("board_sampler")
    conditioners = meta.get("conditioners")
    assert conditioners and "texture" in conditioners and "spr_bin" in conditioners
