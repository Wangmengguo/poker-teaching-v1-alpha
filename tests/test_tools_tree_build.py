import json
from pathlib import Path

from tools import build_tree

CONFIG_PATH = Path("configs/trees/hu_discrete_2cap.yaml")


def _build_tree(tmp_path):
    out_path = tmp_path / "tree_flat.json"
    rc = build_tree.main(
        [
            "--config",
            str(CONFIG_PATH),
            "--out",
            str(out_path),
        ]
    )
    assert rc == 0
    assert out_path.exists()
    return json.loads(out_path.read_text())


def test_tree_build_generates_flat_json(tmp_path):
    artifact = _build_tree(tmp_path)
    nodes = artifact.get("nodes")
    assert isinstance(nodes, list) and nodes, "nodes array must be present"
    for node in nodes:
        assert {"node_id", "street", "actions"} <= node.keys()
        assert isinstance(node["actions"], list)
        for action in node["actions"]:
            assert "name" in action
            assert set(action.keys()) <= {"name", "size_tag", "next"}
    # Ensure edges present via `next`
    assert any(a.get("next") for node in nodes for a in node["actions"] if a.get("next"))


def test_tree_is_2cap_validated(tmp_path):
    artifact = _build_tree(tmp_path)
    nodes = {node["node_id"]: node for node in artifact["nodes"]}

    for node in nodes.values():
        raises = int(node.get("rcap", {}).get("raises", 0))
        assert raises <= 2

    roots = [n_id for n_id, node in nodes.items() if node.get("parent") is None]
    assert roots, "at least one root node expected"

    def _dfs(node_id, raise_counts):
        node = nodes[node_id]
        street = node.get("street")
        current = raise_counts.get(street, 0)
        for action in node.get("actions", []):
            child_counts = dict(raise_counts)
            if action["name"] in {"raise", "bet"}:
                child_counts[street] = child_counts.get(street, current) + 1
                assert child_counts[street] <= 2
            nxt = action.get("next")
            if nxt and nxt in nodes:
                _dfs(nxt, child_counts)

    for root in roots:
        _dfs(root, {})
