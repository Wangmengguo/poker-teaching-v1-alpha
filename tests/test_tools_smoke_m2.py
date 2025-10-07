from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from tools import export_policy  # noqa: F401  # Ensure module import coverage
from tools import m2_smoke


def _read_report(report_path: Path) -> list[str]:
    return report_path.read_text().splitlines()


def test_m2_smoke_generates_all_artifacts(tmp_path):
    report_path = tmp_path / "reports" / "m2_smoke.md"
    exit_code = m2_smoke.main(
        [
            "--out",
            str(report_path),
            "--workspace",
            str(tmp_path),
            "--quick",
        ]
    )
    assert exit_code == 0

    policies_dir = tmp_path / "artifacts" / "policies"
    assert (policies_dir / "preflop.npz").exists()
    assert (policies_dir / "postflop.npz").exists()
    assert report_path.exists()

    # ensure NPZ files have expected structure
    preflop = np.load(policies_dir / "preflop.npz", allow_pickle=True)
    assert set(preflop.files) >= {"node_keys", "actions", "weights", "meta", "table_meta"}


def test_m2_smoke_reports_pass_summary(tmp_path):
    report_path = tmp_path / "reports" / "m2_smoke.md"
    m2_smoke.main(
        [
            "--out",
            str(report_path),
            "--workspace",
            str(tmp_path),
            "--quick",
        ]
    )

    lines = _read_report(report_path)
    assert lines[0].startswith("PASS")
    joined = "\n".join(lines)
    assert "solver_backend" in joined
    assert "policies/preflop.npz" in joined


def test_m2_smoke_handles_partial_artifacts(tmp_path):
    policies_dir = tmp_path / "artifacts" / "policies"
    policies_dir.mkdir(parents=True)
    placeholder = policies_dir / "preflop.npz"
    placeholder.write_bytes(b"placeholder")

    report_path = tmp_path / "reports" / "m2_smoke.md"
    m2_smoke.main(
        [
            "--out",
            str(report_path),
            "--workspace",
            str(tmp_path),
            "--quick",
            "--reuse",
        ]
    )

    lines = _read_report(report_path)
    joined = "\n".join(lines)
    assert "preflop.npz" in joined
    assert "reused=true" in joined
    assert "postflop.npz" in joined
    assert "reused=false" in joined


def test_m2_smoke_reports_small_engine_aggregates(tmp_path):
    report_path = tmp_path / "reports" / "m2_smoke.md"
    exit_code = m2_smoke.main(
        [
            "--out",
            str(report_path),
            "--workspace",
            str(tmp_path),
            "--quick",
        ]
    )
    assert exit_code == 0

    lines = _read_report(report_path)
    count_line = next(line for line in lines if line.startswith("small_engine_used_count="))
    ratio_line = next(line for line in lines if line.startswith("small_engine_used_ratio="))
    sample_line = next(line for line in lines if line.startswith("small_methods_sample="))

    _, count_value = count_line.split("=", maxsplit=1)
    assert int(count_value) >= 0

    _, ratio_value = ratio_line.split("=", maxsplit=1)
    assert 0.0 <= float(ratio_value) <= 1.0

    _, sample_value = sample_line.split("=", maxsplit=1)
    parsed = json.loads(sample_value)
    assert "method" in parsed
    assert "reduced_shape" in parsed
