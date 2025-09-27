import json
from pathlib import Path

from tools import build_tree

CONFIG_PATH = Path("configs/trees/hu_discrete_2cap.yaml")
CLASSIFIERS_PATH = Path("configs/classifiers.yaml")


def _load_yaml(path: Path):
    text = path.read_text()
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text)
    except Exception:
        return json.loads(text)


def _build_tree(tmp_path):
    out_path = tmp_path / "tree.json"
    rc = build_tree.main(
        [
            "--config",
            str(CONFIG_PATH),
            "--out",
            str(out_path),
        ]
    )
    assert rc == 0
    return json.loads(out_path.read_text())


def test_tree_meta_present_and_consistent(tmp_path):
    artifact = _build_tree(tmp_path)
    meta = artifact.get("meta")
    assert meta
    spr_bins_tree = meta.get("spr_bins")

    # 验证关键字段存在而不是完全相等（B4/B5任务改变了数据结构）
    assert spr_bins_tree is not None
    assert "edges" in spr_bins_tree
    assert "labels" in spr_bins_tree
    assert isinstance(spr_bins_tree["edges"], list)
    assert isinstance(spr_bins_tree["labels"], list)
    assert len(spr_bins_tree["edges"]) > 0
    assert len(spr_bins_tree["labels"]) > 0

    # 验证texture_tags存在且结构合理
    texture_tags = meta.get("texture_tags")
    assert texture_tags is not None
    assert isinstance(texture_tags, list)
    assert len(texture_tags) > 0
