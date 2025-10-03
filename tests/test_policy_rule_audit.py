from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from tools import audit_policy_vs_rules


def _write_policy(tmp_path: Path, weights: tuple[float, float]) -> Path:
    path = tmp_path / "policies"
    path.mkdir()
    node_key = "flop|single_raised|caller|oop|texture=dry|spr=spr4|facing=na|hand=top_pair"
    np.savez(
        path / "postflop.npz",
        node_keys=np.array([node_key], dtype=object),
        actions=np.array([("bet", "check")], dtype=object),
        weights=np.array([weights], dtype=object),
        size_tags=np.array([("third", None)], dtype=object),
        meta=np.array(
            [
                {
                    "node_key": node_key,
                    "actions": ["bet", "check"],
                    "size_tags": ["third", None],
                    "weights": list(weights),
                    "zero_weight_actions": [],
                    "node_key_components": {
                        "street": "flop",
                        "pot_type": "single_raised",
                        "role": "caller",
                        "pos": "oop",
                        "texture": "dry",
                        "spr": "spr4",
                        "facing": "na",
                        "bucket": "na",
                    },
                }
            ],
            dtype=object,
        ),
        table_meta=np.array(
            [
                {
                    "version": "audit_v1",
                    "policy_hash": "hash_xyz",
                }
            ],
            dtype=object,
        ),
    )
    return path


def _write_rules(path: Path, *, bet_weight: float, check_weight: float) -> Path:
    data = {
        "flop|single_raised|caller|oop|texture=dry|spr=spr4|facing=na|hand=top_pair": {
            "actions": {
                "bet": bet_weight,
                "check": check_weight,
            },
            "size_tag": "third",
        }
    }
    rules_path = path / "rules.json"
    rules_path.write_text(json.dumps(data))
    return rules_path


def test_policy_vs_rule_diff_report(tmp_path: Path) -> None:
    policy_dir = _write_policy(tmp_path, (0.7, 0.3))
    rules_path = _write_rules(tmp_path, bet_weight=1.0, check_weight=0.0)
    out_path = tmp_path / "audit.md"

    exit_code = audit_policy_vs_rules.main(
        [
            "--policy",
            str(policy_dir),
            "--rules",
            str(rules_path),
            "--out",
            str(out_path),
            "--top",
            "5",
        ]
    )

    assert exit_code == 0
    assert out_path.exists()
    content = out_path.read_text()
    assert "flop|single_raised|caller|oop" in content
    assert "bet" in content and "check" in content


def test_audit_handles_missing_policy_entries(tmp_path: Path) -> None:
    policy_dir = _write_policy(tmp_path, (0.5, 0.5))
    rules_path = _write_rules(tmp_path, bet_weight=1.0, check_weight=0.0)
    out_path = tmp_path / "audit.md"

    # Extend rules with an extra node that is absent from the policy.
    extra = {
        "river|single_raised|caller|ip|texture=wet|spr=low|facing=na|hand=flush": {
            "actions": {"check": 1.0},
            "size_tag": "na",
        }
    }
    existing = json.loads(rules_path.read_text())
    existing.update(extra)
    rules_path.write_text(json.dumps(existing))

    exit_code = audit_policy_vs_rules.main(
        [
            "--policy",
            str(policy_dir),
            "--rules",
            str(rules_path),
            "--out",
            str(out_path),
        ]
    )

    assert exit_code == 0
    content = out_path.read_text()
    assert "missing" in content.lower()
    assert "river|single_raised|caller|ip" in content


def test_audit_cli_returns_nonzero_on_threshold_exceed(tmp_path: Path) -> None:
    policy_dir = _write_policy(tmp_path, (0.7, 0.3))
    rules_path = _write_rules(tmp_path, bet_weight=0.0, check_weight=1.0)
    out_path = tmp_path / "audit.md"

    exit_code = audit_policy_vs_rules.main(
        [
            "--policy",
            str(policy_dir),
            "--rules",
            str(rules_path),
            "--out",
            str(out_path),
            "--threshold",
            "0.2",
        ]
    )

    assert exit_code != 0
    assert out_path.exists()
    content = out_path.read_text()
    assert "threshold" in content.lower()
