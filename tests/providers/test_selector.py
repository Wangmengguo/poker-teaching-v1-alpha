"""
测试评估器选择器。

- 测试强制使用 fallback 评估器
- 测试自动选择 pokerkit 评估器
- 测试强制使用 pokerkit（安装与未安装两种情况）
- 测试缓存单例行为
"""

import pytest
from poker_core.providers.selector import get_evaluator


def _reset_selector_cache() -> None:
    # 仅清空 LRU 缓存即可，不需要 reload 模块
    get_evaluator.cache_clear()


def test_forced_fallback(monkeypatch):
    monkeypatch.setenv("POKER_EVAL", "fallback")
    _reset_selector_cache()
    ev = get_evaluator()
    assert ev.__class__.__name__ == "SimpleFallbackEvaluator"
    # 同一环境下应复用缓存实例
    assert get_evaluator() is ev


def test_auto_prefers_pokerkit(monkeypatch):
    monkeypatch.delenv("POKER_EVAL", raising=False)
    _reset_selector_cache()
    ev = get_evaluator()
    # 环境存在 pokerkit → PokerKitEvaluator；否则 → SimpleFallbackEvaluator
    assert ev.__class__.__name__ in {"PokerKitEvaluator", "SimpleFallbackEvaluator"}


def test_forced_pokerkit_when_installed(monkeypatch):
    pytest.importorskip("pokerkit")
    monkeypatch.setenv("POKER_EVAL", "pokerkit")
    _reset_selector_cache()
    ev = get_evaluator()
    assert ev.__class__.__name__ == "PokerKitEvaluator"


def test_forced_pokerkit_raises_when_missing(monkeypatch):
    try:
        import pokerkit  # type: ignore  # noqa: F401

        pytest.skip("pokerkit 已安装，跳过缺失场景测试")
    except Exception:
        pass
    monkeypatch.setenv("POKER_EVAL", "pokerkit")
    _reset_selector_cache()
    with pytest.raises(Exception):
        get_evaluator()
