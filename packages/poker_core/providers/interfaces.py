"""
提供评估 7 张牌强度的接口。

- 使用 `HandEvaluator` 接口，实现 `evaluate7` 方法
- 返回 `EvalResult` 对象，包含最佳五张牌和强度值
- 强度值是一个可比较的对象，用于比较两张手牌的强度
- 可选的教学分类（先留空，或简单实现）
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class EvalResult:
    # 最佳五张，按我们系统统一字符串，如 ['Ts','Js','Qs','Ks','As']
    best5: list[str]
    # 一个“可比较”的强度值（不暴露三方类型）
    strength: Any
    # 可选的教学分类（先留空，或简单实现）
    category: str | None = None


class HandEvaluator(Protocol):
    def evaluate7(self, hole: Sequence[str], board: Sequence[str]) -> EvalResult: ...


class Strength:
    __slots__ = ("_impl",)

    def __init__(self, impl):
        self._impl = impl

    def __lt__(self, other):
        return self._impl < other._impl

    def __eq__(self, other):
        return self._impl == other._impl

    def __repr__(self):
        return "<Strength …>"


class EvaluationError(Exception):
    """评估器统一异常类型"""

    def __init__(self, error_type: str, detail: Any = None, original: str = None):
        self.error_type = error_type
        self.detail = detail
        self.original = original
        super().__init__(f"{error_type}: {detail or original or 'evaluation failed'}")
