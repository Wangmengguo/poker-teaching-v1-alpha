"""G7 — Policy coverage and facing dimension audit tests.

These tests verify that exported policy tables include the facing dimension
and that basic metadata is consistent with expectations.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from tools import build_policy_solution
from tools import export_policy


def _build_and_export(workspace: Path, *, seed: int = 11) -> Path:
    solution = build_policy_solution.build_solution_from_configs(workspace, seed=seed)
    out_dir = workspace / "artifacts" / "policies"
    out_dir.mkdir(parents=True, exist_ok=True)
    export_policy.export_from_solution(
        solution,
        out_dir=out_dir,
        compress=False,
        skip_existing=False,
        debug_jsonl=None,
        solution_path=workspace / "artifacts" / "policy_solution.json",
    )
    return out_dir


def test_policy_table_includes_facing_and_consistent_meta(tmp_path: Path) -> None:
    # Copy configs from repo into temp workspace
    repo_root = Path.cwd()
    (tmp_path / "configs").mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copytree(repo_root / "configs", tmp_path / "configs", dirs_exist_ok=True)

    policy_dir = _build_and_export(tmp_path, seed=19)

    # Load postflop table and assert facing coverage exists
    with np.load(policy_dir / "postflop.npz", allow_pickle=True) as z:
        node_keys = [str(x) for x in list(z["node_keys"])]
        meta = list(z["meta"])  # array of dicts
        table_meta = z["table_meta"][0]

        # Ensure node_count matches length
        if isinstance(table_meta, dict) and "node_count" in table_meta:
            assert int(table_meta["node_count"]) == len(node_keys)

        # At least one node with facing dimension present
        assert any("|facing=" in nk for nk in node_keys)

        # Components must include facing for every node
        for m in meta[:50]:  # sample a subset for speed
            comp = m.get("node_key_components", {}) if isinstance(m, dict) else {}
            assert "facing" in comp

    # Preflop table should have facing=na entries and texture/spr=na
    with np.load(policy_dir / "preflop.npz", allow_pickle=True) as z:
        node_keys = [str(x) for x in list(z["node_keys"])][:20]
        assert all("texture=na" in nk and "spr=na" in nk and "facing=na" in nk for nk in node_keys)
