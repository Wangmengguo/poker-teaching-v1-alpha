import json
from pathlib import Path

import pytest

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


def test_invalid_node_reference_raises_error(tmp_path):
    """测试无效的节点引用会引发验证错误"""
    # 创建一个包含无效节点引用的配置
    invalid_config = {
        "nodes": [
            {
                "id": "root",
                "street": "preflop",
                "role": "ip",
                "actions": [{"name": "fold", "next": "nonexistent_node"}],  # 引用不存在的节点
            }
        ]
    }

    # 写入临时配置文件
    config_path = tmp_path / "invalid_config.yaml"
    import yaml

    with open(config_path, "w") as f:
        yaml.dump(invalid_config, f)

    out_path = tmp_path / "tree.json"

    # 应该引发ValueError
    with pytest.raises(ValueError, match="references unknown target node 'nonexistent_node'"):
        build_tree.main(["--config", str(config_path), "--out", str(out_path)])


def test_valid_node_references_pass_validation(tmp_path):
    """测试有效的节点引用通过验证"""
    # 创建一个包含有效节点引用的配置
    valid_config = {
        "nodes": [
            {
                "id": "root",
                "street": "preflop",
                "role": "ip",
                "actions": [{"name": "fold", "next": "terminal"}],  # 引用存在的节点
            },
            {"id": "terminal", "street": "preflop", "role": "terminal", "actions": []},
        ],
        "terminals": ["terminal"],  # 明确定义terminals
    }

    # 写入临时配置文件
    config_path = tmp_path / "valid_config.yaml"
    import yaml

    with open(config_path, "w") as f:
        yaml.dump(valid_config, f)

    out_path = tmp_path / "tree.json"

    # 应该成功构建
    rc = build_tree.main(["--config", str(config_path), "--out", str(out_path)])
    assert rc == 0
    assert out_path.exists()


def test_null_terminals_handling(tmp_path):
    """测试terminals: null的正确处理"""
    # 创建一个包含null terminals的配置
    null_terminals_config = {
        "nodes": [
            {
                "id": "root",
                "street": "preflop",
                "role": "ip",
                "actions": [{"name": "fold", "next": "terminal"}],  # 引用存在的节点
            },
            {"id": "terminal", "street": "preflop", "role": "terminal", "actions": []},
        ],
        "terminals": None,  # YAML中的null值
    }

    # 写入临时配置文件
    config_path = tmp_path / "null_terminals_config.yaml"
    import yaml

    with open(config_path, "w") as f:
        yaml.dump(null_terminals_config, f)

    out_path = tmp_path / "tree.json"

    # 应该成功构建，null terminals应该被当作空列表处理
    rc = build_tree.main(["--config", str(config_path), "--out", str(out_path)])
    assert rc == 0
    assert out_path.exists()

    # 验证输出中的terminals字段
    artifact = json.loads(out_path.read_text())
    assert artifact["terminals"] == []  # 应该被转换为空列表


def test_missing_terminals_handling(tmp_path):
    """测试缺少terminals字段的正确处理"""
    # 创建一个缺少terminals字段的配置
    no_terminals_config = {
        "nodes": [
            {
                "id": "root",
                "street": "preflop",
                "role": "ip",
                "actions": [{"name": "fold", "next": "terminal"}],  # 引用存在的节点
            },
            {"id": "terminal", "street": "preflop", "role": "terminal", "actions": []},
        ]
        # 完全没有terminals字段
    }

    # 写入临时配置文件
    config_path = tmp_path / "no_terminals_config.yaml"
    import yaml

    with open(config_path, "w") as f:
        yaml.dump(no_terminals_config, f)

    out_path = tmp_path / "tree.json"

    # 应该成功构建，缺失terminals应该被当作空列表处理
    rc = build_tree.main(["--config", str(config_path), "--out", str(out_path)])
    assert rc == 0
    assert out_path.exists()

    # 验证输出中的terminals字段
    artifact = json.loads(out_path.read_text())
    assert artifact["terminals"] == []  # 应该被转换为空列表
