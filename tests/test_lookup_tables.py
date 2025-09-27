import json
from pathlib import Path

import numpy as np

from packages.poker_core.suggest import lookup
from tools import build_lookup

LOOKUP_DIR = Path("artifacts/lookup")


def _ensure_tables():
    build_lookup.main(
        [
            "--type",
            "hs",
            "--streets",
            "preflop,flop,turn",
            "--out",
            str(LOOKUP_DIR),
        ]
    )
    build_lookup.main(
        [
            "--type",
            "pot",
            "--streets",
            "flop,turn",
            "--out",
            str(LOOKUP_DIR),
        ]
    )


def _load_npz(path: Path):
    payload = np.load(path, allow_pickle=True)
    meta = json.loads(str(payload["meta"].item()))
    return payload, meta


def test_lookup_files_exist_and_shapes(tmp_path):
    _ensure_tables()
    hs_flop = LOOKUP_DIR / "hs_flop.npz"
    pot_turn = LOOKUP_DIR / "pot_turn.npz"
    assert hs_flop.exists()
    assert pot_turn.exists()

    payload, meta = _load_npz(hs_flop)
    values = payload["values"]
    # 适配新的lookup表结构（B4/B5任务后结构变化）
    assert values.shape[0] == 3  # 第一个维度保持不变
    assert values.shape[2] == 8  # 第三个维度保持不变
    assert values.shape[1] >= 3  # 第二个维度可能变化（从3变为5）
    assert meta["kind"] == "hs"

    payload_pot, meta_pot = _load_npz(pot_turn)
    pot_values = payload_pot["values"]
    assert pot_values.shape[0] == 3  # 第一个维度保持不变
    assert pot_values.shape[2] == 8  # 第三个维度保持不变
    assert pot_values.shape[1] >= 3  # 第二个维度可能变化
    assert meta_pot["kind"] == "pot"


def test_lookup_api_present_and_fallback():
    _ensure_tables()
    value = lookup.hs_lookup.get("flop", "dry", "low", 2)
    assert 0.0 <= value <= 1.0

    fallback = lookup.outs_to_river()
    missing = lookup.hs_lookup.get("flop", "unknown_texture", "low", 2)
    assert abs(missing - fallback) < 1e-6


def test_outs_to_river_zero_handling():
    """测试 outs=0 的正确处理 - 这是 poker 中的有效情况（drawing dead）"""
    # outs=0 应该返回 0.0，而不是默认值
    result_zero = lookup.outs_to_river(outs=0)
    assert result_zero == 0.0, f"Expected 0.0 for outs=0, got {result_zero}"

    # 验证质量权重对零outs的影响
    result_zero_flush = lookup.outs_to_river(outs=0, quality="flush")
    assert (
        result_zero_flush == 0.0
    ), f"Expected 0.0 for outs=0 with flush quality, got {result_zero_flush}"

    # 对比：outs=None 应该使用默认值
    result_none = lookup.outs_to_river(None)
    expected_default = 8 * 0.021  # 8 outs * 2.1% per out
    assert (
        abs(result_none - expected_default) < 1e-6
    ), f"Expected default value for None, got {result_none}"


def test_outs_to_river_quality_weights():
    """测试不同质量权重的正确应用"""
    base_outs = 5
    base_prob = 5 * 0.021  # 10.5%

    # 标准权重
    standard = lookup.outs_to_river(base_outs, "standard")
    assert abs(standard - base_prob) < 1e-6

    # 同花权重应该更高
    flush = lookup.outs_to_river(base_outs, "flush")
    expected_flush = base_prob * 1.05
    assert abs(flush - expected_flush) < 1e-6

    # 顺子权重应该稍低
    straight = lookup.outs_to_river(base_outs, "straight")
    expected_straight = base_prob * 0.95
    assert abs(straight - expected_straight) < 1e-6


def test_outs_to_river_bounds():
    """测试返回值边界"""
    # 零outs应该返回0.0
    assert lookup.outs_to_river(0) == 0.0

    # 负数outs应该返回0.0（边界检查）
    assert lookup.outs_to_river(-1) == 0.0

    # 大量outs应该被限制在0.95
    high_outs = lookup.outs_to_river(50)  # 50 * 0.021 = 1.05，会被限制到0.95
    assert high_outs == 0.95
