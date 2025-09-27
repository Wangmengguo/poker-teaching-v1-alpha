from pathlib import Path

from tools import m1_smoke


def _run_smoke(tmp_path):
    workspace = tmp_path / "workspace"
    out_path = tmp_path / "report.md"
    rc = m1_smoke.main(
        [
            "--workspace",
            str(workspace),
            "--out",
            str(out_path),
            "--quick",
            "--seed",
            "7",
        ]
    )
    return rc, workspace, out_path


def test_smoke_runs_and_generates_report(tmp_path):
    rc, workspace, report = _run_smoke(tmp_path)
    assert rc == 0
    assert report.exists()
    content = report.read_text()
    assert content.splitlines()[0].startswith("PASS")
    # basic sanity: run should produce at least one bucket file
    assert (workspace / "configs" / "buckets" / "preflop.json").exists()


def test_smoke_validates_outputs_present(tmp_path):
    rc, workspace, report = _run_smoke(tmp_path)
    assert rc == 0
    expected_files = [
        workspace / "configs" / "buckets" / "preflop.json",
        workspace / "configs" / "buckets" / "flop.json",
        workspace / "configs" / "buckets" / "turn.json",
        workspace / "artifacts" / "transitions" / "flop_to_turn.json",
        workspace / "artifacts" / "transitions" / "turn_to_river.json",
        workspace / "artifacts" / "ev_cache" / "turn_leaf.npz",
        workspace / "artifacts" / "tree_flat.json",
    ]
    for path in expected_files:
        assert path.exists(), f"missing expected artifact {path}"
    assert "PASS" in report.read_text()
