"""Build a flattened HU discrete 2-cap tree artifact from YAML config."""

from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path
from typing import Any


def _load_config(path: Path) -> dict[str, Any]:
    text = path.read_text()
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
    except Exception:
        data = json.loads(text)
    if not isinstance(data, dict):  # pragma: no cover - safety net
        raise ValueError("tree config must be a mapping")
    return data


def _normalize_action(action: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": action.get("name"),
    }
    if action.get("size_tag"):
        result["size_tag"] = action["size_tag"]
    if action.get("next"):
        result["next"] = action["next"]
    return result


def _build_nodes(config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    nodes_cfg = config.get("nodes") or []
    if not isinstance(nodes_cfg, list):
        raise ValueError("config.nodes must be a list")

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    node_ids: set[str] = set()

    # 收集所有有效的目标节点ID（包括terminals）
    terminals_cfg = config.get("terminals") or []
    terminals = set(terminals_cfg)
    valid_targets = set()

    # 首先收集所有节点ID
    for raw_node in nodes_cfg:
        node_id = raw_node.get("id")
        if not node_id:
            raise ValueError("Each node requires an id")
        if node_id in node_ids:
            raise ValueError(f"Duplicate node id: {node_id}")
        node_ids.add(node_id)
        valid_targets.add(node_id)

    # 添加terminals到有效目标集合
    valid_targets.update(terminals)

    # 构建节点和边
    for raw_node in nodes_cfg:
        node_id = raw_node.get("id")
        actions_raw = raw_node.get("actions") or []
        actions = [_normalize_action(a) for a in actions_raw]
        node = {
            "node_id": node_id,
            "parent": raw_node.get("parent"),
            "street": raw_node.get("street"),
            "role": raw_node.get("role"),
            "facing": raw_node.get("facing"),
            "rcap": raw_node.get("rcap", {}),
            "actions": actions,
        }
        nodes.append(node)
        for action in actions:
            if action.get("next"):
                next_node = action["next"]
                if next_node not in valid_targets:
                    raise ValueError(
                        f"Node '{node_id}' action '{action['name']}' references unknown target node '{next_node}'. "
                        f"Valid targets are: {sorted(valid_targets)}"
                    )
                edges.append(
                    {
                        "from": node_id,
                        "action": action["name"],
                        "to": action["next"],
                    }
                )
    return nodes, edges


def _validate_two_cap(nodes: list[dict[str, Any]], max_cap: int = 2) -> None:
    graph = {node["node_id"]: node for node in nodes}
    roots = [node_id for node_id, node in graph.items() if node.get("parent") is None]
    if not roots:
        raise ValueError("Tree must contain at least one root node")

    for node in nodes:
        raises = int(node.get("rcap", {}).get("raises", 0))
        if raises > max_cap:
            raise ValueError(f"Node {node['node_id']} exceeds raise cap {max_cap}")

    for root in roots:
        stack: deque[tuple[str, dict[str, int]]] = deque([(root, {})])
        while stack:
            node_id, raise_counts = stack.pop()
            node = graph[node_id]
            street = node.get("street") or "unknown"
            for action in node.get("actions", []):
                next_counts = dict(raise_counts)
                if action.get("name") in {"raise", "bet"}:
                    next_counts[street] = next_counts.get(street, 0) + 1
                    if next_counts[street] > max_cap:
                        raise ValueError(
                            f"Raise cap exceeded on street {street} via node {node_id}"
                        )
                nxt = action.get("next")
                if nxt and nxt in graph:
                    stack.append((nxt, next_counts))


def build_tree_artifact(config_path: Path) -> dict[str, Any]:
    config = _load_config(config_path)
    meta = config.get("meta") or {}
    nodes, edges = _build_nodes(config)
    max_cap = int(meta.get("max_raise_cap", 2))
    _validate_two_cap(nodes, max_cap=max_cap)
    return {
        "meta": meta,
        "nodes": nodes,
        "edges": edges,
        "terminals": config.get("terminals") or [],
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build flattened tree artifact")
    parser.add_argument("--config", required=True, help="Path to tree YAML config")
    parser.add_argument("--out", required=True, help="Output JSON path")
    return parser.parse_args(argv)


def write_tree(artifact: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(artifact, fh, indent=2, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    config_path = Path(args.config)
    artifact = build_tree_artifact(config_path)
    write_tree(artifact, Path(args.out))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
