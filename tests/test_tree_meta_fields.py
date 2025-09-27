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
    classifiers = _load_yaml(CLASSIFIERS_PATH)
    spr_bins_tree = meta.get("spr_bins")
    spr_bins_cfg = classifiers.get("spr_bins")
    assert spr_bins_tree == spr_bins_cfg
    texture_tags = meta.get("texture_tags")
    assert texture_tags == classifiers.get("texture_tags")
