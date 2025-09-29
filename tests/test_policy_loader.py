import os
import time
from pathlib import Path

import numpy as np
import pytest
from poker_core.suggest.policy_loader import PolicyLoader


class DummyMetrics:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def increment(self, name: str, **labels: object) -> None:
        self.calls.append((name, labels))


def _write_policy_npz(path: Path, *, weight_scale: float = 1.0) -> None:
    node_keys = np.array(
        [
            "flop|single_raised|caller|oop|texture=dry|spr=spr4|hand=top_pair",
        ],
        dtype=object,
    )
    actions = np.array(
        [
            ("bet", "check"),
        ],
        dtype=object,
    )
    weights = np.array(
        [
            (0.6 * weight_scale, 0.4 * weight_scale),
        ],
        dtype=object,
    )
    size_tags = np.array(
        [
            ("third", None),
        ],
        dtype=object,
    )
    meta = np.array(
        [
            {
                "node_key": node_keys[0],
                "actions": list(actions[0]),
                "size_tags": ["third", None],
                "weights": [0.6 * weight_scale, 0.4 * weight_scale],
                "zero_weight_actions": [],
                "node_key_components": {
                    "street": "flop",
                    "pot_type": "single_raised",
                    "role": "caller",
                    "pos": "oop",
                    "texture": "dry",
                    "spr": "spr4",
                    "bucket": "na",
                },
            }
        ],
        dtype=object,
    )
    table_meta = np.array(
        [
            {
                "version": "test_v1",
                "policy_hash": "hash123",
            }
        ],
        dtype=object,
    )
    np.savez(
        path,
        node_keys=node_keys,
        actions=actions,
        weights=weights,
        size_tags=size_tags,
        meta=meta,
        table_meta=table_meta,
    )


def test_loader_reads_npz_and_normalizes_weights(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.npz"
    _write_policy_npz(policy_path, weight_scale=0.5)

    loader = PolicyLoader(policy_path)
    entry = loader.lookup("flop|single_raised|caller|oop|texture=dry|spr=spr4|hand=top_pair")

    assert entry is not None
    assert entry.node_key == "flop|single_raised|caller|oop|texture=dry|spr=spr4|hand=top_pair"
    assert pytest.approx(sum(entry.weights)) == 1.0
    assert entry.actions == ("bet", "check")
    assert entry.size_tags[0] == "third"
    assert entry.table_meta["policy_hash"] == "hash123"


def test_loader_handles_missing_node(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    policy_path = tmp_path / "policy.npz"
    _write_policy_npz(policy_path)

    metrics = DummyMetrics()
    loader = PolicyLoader(policy_path, metrics=metrics)

    with caplog.at_level("INFO"):
        result = loader.lookup("missing|node")

    assert result is None
    assert any("policy_lookup_miss" in message for message in caplog.messages)
    assert metrics.calls
    name, labels = metrics.calls[0]
    assert name == "policy_lookup_miss"
    assert labels.get("node_key") == "missing|node"


def test_loader_refresh_on_file_change(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.npz"
    _write_policy_npz(policy_path)

    loader = PolicyLoader(policy_path)
    first = loader.lookup("flop|single_raised|caller|oop|texture=dry|spr=spr4|hand=top_pair")
    assert first is not None
    assert pytest.approx(first.weights[0]) == 0.6

    time.sleep(0.01)
    _write_policy_npz(policy_path, weight_scale=2.0)
    os.utime(policy_path, None)

    second = loader.lookup("flop|single_raised|caller|oop|texture=dry|spr=spr4|hand=top_pair")
    assert second is not None
    assert pytest.approx(second.weights[0]) == 0.6  # normalized from scaled weights
    assert second.table_meta["version"] == "test_v1"
