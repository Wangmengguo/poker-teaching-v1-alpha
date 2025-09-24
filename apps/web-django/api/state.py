"""
Simple in-memory stores for demo purposes
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

# 进程内最小状态存储（教学期用；重启会清空）
SESSIONS: dict[str, Any] = {}
HANDS: dict[str, Any] = {}
REPLAYS = {}
METRICS = {
    "deals_total": 0,
    "last_latency_ms": None,
    "error_total": 0,
}


def snapshot_state(gs: Any) -> dict:
    """
    把领域层 GameState 转成给 API 的最小视图，避免泄露内部实现。
    你可按自己的 GameState 字段名做适配。
    """

    def to_dict(x):
        if is_dataclass(x):
            return asdict(x)
        if hasattr(x, "__dict__"):
            return dict(x.__dict__)
        return x

    s = to_dict(gs)
    # 规范化输出字段（按你的 GameState 实际字段调整）
    out = {
        "street": s.get("street"),
        "board": s.get("board", []),
        "to_act": s.get("to_act"),
        "button": s.get("button"),
        "pot": s.get("pot"),
        "players": [],
    }
    # players: 只暴露必要字段（stack/hole 可按权限裁剪）
    for p in s.get("players", []):
        if is_dataclass(p):
            p = asdict(p)
        out["players"].append(
            {
                "stack": p.get("stack"),
                # 将引擎的 invested_street 暴露为 bet，便于 UI 一致理解
                "bet": p.get("invested_street", p.get("bet", 0)),
                # 教学期可直接返回 hole；将来要做权限/隐藏
                "hole": p.get("hole", []),
            }
        )
    # legal_actions 调用领域函数（由视图层负责调用更合适，这里留出位）
    return out
