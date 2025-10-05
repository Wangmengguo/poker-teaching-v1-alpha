import shutil
from pathlib import Path

import pytest

from tools.build_policy_solution import build_solution_from_configs

REPO_ROOT = Path(__file__).resolve().parents[1]


def _nodes_by_facing(solution, facing: str) -> list[dict]:
    return [node for node in solution["nodes"] if node.get("facing") == facing]


def _fold_weight(node: dict) -> float:
    for action in node.get("actions", []):
        if action.get("action") == "fold":
            return float(action.get("weight", 0.0))
    raise AssertionError("fold action missing")


@pytest.fixture(scope="module")
def base_solution():
    return build_solution_from_configs(REPO_ROOT)


@pytest.fixture
def copied_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    src = REPO_ROOT / "configs"
    shutil.copytree(src, workspace / "configs")
    return workspace


def test_facing_dimensions_exported(base_solution):
    assert _nodes_by_facing(base_solution, "third"), "expected facing=third nodes"
    assert _nodes_by_facing(base_solution, "half"), "expected facing=half nodes"
    assert _nodes_by_facing(base_solution, "two_third+"), "expected facing=two_third+ nodes"
    assert _nodes_by_facing(base_solution, "na"), "expected facing=na nodes"


def test_facing_weights_calculated_correctly(base_solution):
    flop_third = next(
        node for node in _nodes_by_facing(base_solution, "third") if node.get("street") == "flop"
    )
    flop_half = next(
        node for node in _nodes_by_facing(base_solution, "half") if node.get("street") == "flop"
    )
    flop_large = next(
        node
        for node in _nodes_by_facing(base_solution, "two_third+")
        if node.get("street") == "flop"
    )

    assert _fold_weight(flop_third) == pytest.approx(0.30, abs=0.05)
    assert _fold_weight(flop_half) == pytest.approx(0.50, abs=0.05)
    assert _fold_weight(flop_large) == pytest.approx(0.70, abs=0.05)


def test_facing_defense_action_set(base_solution):
    node = next(
        node
        for node in _nodes_by_facing(base_solution, "half")
        if node.get("street") == "turn" and node.get("role") == "caller"
    )
    actions = {action["action"]: action for action in node["actions"]}
    assert {"call", "fold", "raise"}.issubset(actions)
    assert actions["raise"].get("size_tag")


def test_facing_fallback_to_default(copied_workspace: Path):
    manifest_text = """
    facing_defaults:
      third:
        call: 0.6
        fold: 0.2
        raise:
          weight: 0.2
          size_tag: half
      half:
        call: 0.5
        fold: 0.3
        raise:
          weight: 0.2
          size_tag: half
    """.strip()
    manifest_path = copied_workspace / "configs" / "policy_manifest.yaml"
    manifest_path.write_text(manifest_text, encoding="utf-8")

    solution = build_solution_from_configs(copied_workspace)
    fallback_nodes = [
        node
        for node in solution["nodes"]
        if node.get("facing") == "na" and node.get("meta", {}).get("facing_fallback")
    ]
    assert fallback_nodes, "expected at least one fallback node when configs omit two_third+"
    assert any(
        "two_third+" in node.get("meta", {}).get("fallback_from", []) for node in fallback_nodes
    )
