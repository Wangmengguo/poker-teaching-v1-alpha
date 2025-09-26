import json

import pytest

from tools import build_buckets


@pytest.mark.parametrize(
    "streets_arg,bins_arg,expected_bins",
    [
        ("preflop,flop,turn", "6,8,8", {"preflop": 6, "flop": 8, "turn": 8}),
    ],
)
def test_build_buckets_creates_files_and_schema(tmp_path, streets_arg, bins_arg, expected_bins):
    out_dir = tmp_path / "bucket_output"
    argv = [
        "--streets",
        streets_arg,
        "--bins",
        bins_arg,
        "--features",
        "strength,potential",
        "--out",
        str(out_dir),
        "--seed",
        "42",
    ]

    exit_code = build_buckets.main(argv)
    assert exit_code == 0

    for street, bins in expected_bins.items():
        path = out_dir / f"{street}.json"
        assert path.exists(), f"missing bucket file for {street}"
        data = json.loads(path.read_text())
        assert data["version"] == 1
        assert data["bins"] == bins
        assert data["features"] == ["strength", "potential"]
        assert data.get("meta", {}).get("seed") == 42
        labels = data.get("labels")
        assert isinstance(labels, list)
        assert len(labels) == bins
        if street in ("flop", "turn"):
            match_order = data.get("match_order")
            assert match_order == [
                "value_two_pair_plus",
                "overpair_or_tptk",
                "top_pair_weak_or_second",
                "middle_pair_or_third_minus",
                "strong_draw",
                "weak_draw",
                "overcards_no_bdfd",
                "air",
            ]


def test_bucket_mapping_stability_seeded(tmp_path_factory):
    cfg1 = build_buckets.generate_bucket_configs(seed=42)
    cfg2 = build_buckets.generate_bucket_configs(seed=42)
    assert cfg1 == cfg2

    cfg3 = build_buckets.generate_bucket_configs(seed=7)
    assert cfg3 != cfg1

    out1 = tmp_path_factory.mktemp("buckets_seed42_run1")
    out2 = tmp_path_factory.mktemp("buckets_seed42_run2")

    common_args = [
        "--streets",
        "preflop,flop,turn",
        "--bins",
        "6,8,8",
        "--features",
        "strength,potential",
        "--seed",
        "42",
    ]

    exit_code_1 = build_buckets.main(common_args + ["--out", str(out1)])
    exit_code_2 = build_buckets.main(common_args + ["--out", str(out2)])
    assert exit_code_1 == exit_code_2 == 0

    for street in ("preflop", "flop", "turn"):
        path1 = out1 / f"{street}.json"
        path2 = out2 / f"{street}.json"
        assert path1.exists() and path2.exists()
        assert path1.read_text() == path2.read_text()
