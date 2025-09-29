import json
from pathlib import Path

import numpy as np

from tools import export_policy


def _write_solution(tmp_path: Path) -> Path:
    solution = {
        "meta": {
            "solver_backend": "linprog",
            "seed": 123,
            "tree_hash": "abc123",
        },
        "nodes": [
            {
                "node_key": "preflop/single_raised/role:pfr/ip/texture:na/spr:mid/bucket:3",
                "street": "preflop",
                "pot_type": "single_raised",
                "role": "pfr",
                "pos": "ip",
                "texture": "na",
                "spr": "mid",
                "bucket": 3,
                "actions": [
                    {"action": "raise", "size_tag": "2.5x", "weight": 0.75},
                    {"action": "fold", "weight": 0.25},
                ],
            },
            {
                "node_key": "flop/single_raised/role:caller/oop/texture:dry/spr:mid/bucket:5",
                "street": "flop",
                "pot_type": "single_raised",
                "role": "caller",
                "pos": "oop",
                "texture": "dry",
                "spr": "mid",
                "bucket": 5,
                "actions": [
                    {"action": "bet", "size_tag": "33", "weight": 0.0},
                    {"action": "check", "weight": 1.0},
                ],
            },
            {
                "node_key": "turn/single_raised/role:pfr/ip/texture:semi/spr:low/bucket:2",
                "street": "turn",
                "pot_type": "single_raised",
                "role": "pfr",
                "pos": "ip",
                "texture": "semi",
                "spr": "low",
                "bucket": 2,
                "actions": [
                    {"action": "bet", "size_tag": "75", "weight": 0.4},
                    {"action": "check", "weight": 0.6},
                ],
            },
        ],
    }
    path = tmp_path / "solution.json"
    path.write_text(json.dumps(solution, indent=2))
    return path


def test_export_policy_writes_npz_and_metadata(tmp_path):
    solution_path = _write_solution(tmp_path)
    out_dir = tmp_path / "artifacts" / "policies"

    exit_code = export_policy.main(["--solution", str(solution_path), "--out", str(out_dir)])
    assert exit_code == 0

    preflop_path = out_dir / "preflop.npz"
    postflop_path = out_dir / "postflop.npz"

    assert preflop_path.exists()
    assert postflop_path.exists()

    preflop = np.load(preflop_path, allow_pickle=True)
    postflop = np.load(postflop_path, allow_pickle=True)

    for dataset in (preflop, postflop):
        assert set(dataset.files) >= {"node_keys", "actions", "weights", "meta", "table_meta"}
        table_meta = dataset["table_meta"][0]
        assert "generated_at" in table_meta
        assert table_meta["solver_backend"] == "linprog"


def test_policy_export_respects_node_key_schema(tmp_path):
    solution_path = _write_solution(tmp_path)
    out_dir = tmp_path / "out"
    export_policy.main(["--solution", str(solution_path), "--out", str(out_dir)])

    postflop = np.load(out_dir / "postflop.npz", allow_pickle=True)
    node_keys = list(postflop["node_keys"])
    metas = list(postflop["meta"])

    assert len(node_keys) == len(metas) >= 2
    for key, meta in zip(node_keys, metas, strict=True):
        components = meta["node_key_components"]
        assert components["street"] in {"flop", "turn"}
        assert components["pot_type"] == "single_raised"
        assert components["role"].startswith("role:")
        assert components["pos"] in {"ip", "oop"}
        reconstructed = "/".join(
            [
                components["street"],
                components["pot_type"],
                components["role"],
                components["pos"],
                f"texture:{components['texture']}",
                f"spr:{components['spr']}",
                f"bucket:{components['bucket']}",
            ]
        )
        assert reconstructed == key


def test_policy_export_handles_zero_weight_actions(tmp_path):
    solution_path = _write_solution(tmp_path)
    out_dir = tmp_path / "out"
    export_policy.main(["--solution", str(solution_path), "--out", str(out_dir)])

    postflop = np.load(out_dir / "postflop.npz", allow_pickle=True)
    metas = list(postflop["meta"])

    flagged = [meta for meta in metas if meta["zero_weight_actions"]]
    assert flagged, "Expected zero-weight actions to be flagged"
    for meta in flagged:
        for action in meta["zero_weight_actions"]:
            assert isinstance(action, str)
            assert action in meta["actions"]
