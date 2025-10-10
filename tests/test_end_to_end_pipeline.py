"""G7 — End-to-end pipeline smoke tests.

These tests validate that the minimal local pipeline can generate artifacts
and that the audit CLI can run against a tiny rule baseline.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from tools import audit_policy_vs_rules as audit_cli
from tools import build_policy_solution
from tools import export_policy
from tools import m2_smoke


def test_pipeline_generates_complete_artifacts_quick(tmp_path: Path) -> None:
    """Run the quick smoke pipeline into a temp workspace and check outputs."""

    ok, details = m2_smoke.run_smoke(
        workspace=tmp_path,
        quick=True,
        reuse=False,
        force=False,
        seed=123,
    )
    assert ok, f"smoke failed: {details}"

    artifacts = tmp_path / "artifacts"
    reports = tmp_path / "reports"
    assert (artifacts / "lp_solution.json").exists()
    assert (artifacts / "policies" / "preflop.npz").exists()
    assert (artifacts / "policies" / "postflop.npz").exists()
    assert (reports / "m2_eval_sample.json").exists()

    # Validate NPZ schema shape minimally
    for name in ("preflop", "postflop"):
        with np.load(artifacts / "policies" / f"{name}.npz", allow_pickle=True) as z:
            node_keys = list(z["node_keys"])
            actions = list(z["actions"])
            weights = list(z["weights"])
            size_tags = list(z["size_tags"])
            meta = list(z["meta"])
            assert len(node_keys) == len(actions) == len(weights) == len(size_tags) == len(meta)
            assert len(node_keys) >= 1


def test_rule_policy_diff_cli_smoke(tmp_path: Path, monkeypatch) -> None:
    """Build a minimal policy and compare against a tiny ruleset via CLI.

    We generate a policy from repo configs, then create a tiny rules mapping
    for a few node keys. The audit CLI should complete and write a report.
    """

    # Prepare workspace with configs copied from repo
    repo_root = Path.cwd()
    workspace = tmp_path
    (workspace / "configs").mkdir(parents=True, exist_ok=True)

    # Copy entire configs directory for simplicity
    import shutil

    shutil.copytree(repo_root / "configs", workspace / "configs", dirs_exist_ok=True)

    # Build solution and export policies
    solution = build_policy_solution.build_solution_from_configs(workspace, seed=7)
    solution_path = workspace / "artifacts" / "policy_solution.json"
    solution_path.parent.mkdir(parents=True, exist_ok=True)
    solution_path.write_text(json.dumps(solution))

    policy_dir = workspace / "artifacts" / "policies"
    export_policy.export_from_solution(
        solution,
        out_dir=policy_dir,
        compress=False,
        skip_existing=False,
        debug_jsonl=None,
        solution_path=solution_path,
    )

    # Create a tiny rules baseline using a couple of node keys from the table
    with np.load(policy_dir / "postflop.npz", allow_pickle=True) as z:
        node_keys = [str(x) for x in list(z["node_keys"])[:3]]
    rules = {}
    # For each node, build a trivial distribution over actions
    for nk in node_keys:
        rules[nk] = {"actions": {"call": 0.5, "fold": 0.4, "raise": 0.1}}
    rules_path = workspace / "rules.json"
    rules_path.write_text(json.dumps(rules))

    # Run audit CLI with a high threshold so this smoke doesn't fail on diffs
    report_path = workspace / "reports" / "policy_rule_audit.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    rc = audit_cli.main(
        [
            "--policy",
            str(policy_dir),
            "--rules",
            str(rules_path),
            "--out",
            str(report_path),
            "--threshold",
            "1.1",
            "--top",
            "5",
        ]
    )
    assert rc == 0
    assert report_path.exists()
