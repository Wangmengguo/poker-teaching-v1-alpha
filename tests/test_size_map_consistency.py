import json
from pathlib import Path

SIZE_MAP_PATH = Path("configs/size_map.yaml")


def _load_config():
    text = SIZE_MAP_PATH.read_text()
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text)
    except Exception:
        return json.loads(text)


def test_size_tag_bounds():
    data = _load_config()
    assert data is not None
    half = data.get("half")
    assert half and 0.45 <= half[0] < half[1] <= 0.55
    pot = data.get("pot")
    assert pot and 0.95 <= pot[0] < pot[1] <= 1.05
    two_third = data.get("two_third")
    assert two_third and 0.63 <= two_third[0] < two_third[1] <= 0.72
    # ensure tags sorted ascending by midpoint
    tags = list(data.items())
    midpoints = [sum(bounds) / 2 for _, bounds in tags]
    assert midpoints == sorted(midpoints)
