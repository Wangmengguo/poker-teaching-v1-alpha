# packages/poker_core/domain/actions.py
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Literal

# 引擎自由函数接口
from poker_core.state_hu import apply_action as core_apply_action
from poker_core.state_hu import legal_actions as core_legal_actions

ActionName = Literal["fold", "check", "call", "bet", "raise", "allin"]


@dataclass
class LegalAction:
    action: ActionName
    # 仅当 action in {"bet","raise"} 时有效
    min: int | None = None
    max: int | None = None
    # 仅当 action == "call" 时有效
    to_call: int | None = None


def to_act_index(gs) -> int:
    """统一行动者获取入口。对齐 gs.to_act : 0/1。"""
    actor = getattr(gs, "to_act", None)
    if actor not in (0, 1):
        raise ValueError("Invalid gs.to_act; expected 0 or 1")
    return actor


def _simulate_apply(gs, action: ActionName, amount: int | None = None) -> bool:
    """在原始 gs 上尝试执行动作（引擎为纯函数返回新状态，输入不变）。"""
    try:
        # 深拷贝以避免修改原始状态（特别是 events 列表）
        gs_copy = copy.deepcopy(gs)
        if amount is None:
            core_apply_action(gs_copy, action)
        else:
            core_apply_action(gs_copy, action, amount)
        return True
    except Exception:
        return False


def _binary_search_min(gs, action: ActionName, lo: int, hi: int) -> int | None:
    ans = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if _simulate_apply(gs, action, mid):
            ans = mid
            hi = mid - 1
        else:
            lo = mid + 1
    return ans


def _binary_search_max(gs, action: ActionName, lo: int, hi: int) -> int | None:
    ans = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if _simulate_apply(gs, action, mid):
            ans = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return ans


def _compute_to_call(gs, actor: int) -> int:
    me = gs.players[actor]
    other = gs.players[1 - actor]
    return max(other.invested_street - me.invested_street, 0)


def legal_actions_struct(gs) -> list[LegalAction]:
    """
    返回结构化合法动作列表：
    - bet/raise 附带 [min, max]
    - call 附带 to_call
    - 仅返回真实可执行的动作（通过模拟 apply 探测边界）
    """
    # 使用引擎自由函数获取字符串动作集合
    str_acts: list[str] = list(core_legal_actions(gs))
    result: list[LegalAction] = []

    actor = to_act_index(gs)
    bb = int(getattr(gs, "bb", 50))
    actor_stack = int(getattr(gs.players[actor], "stack", 0))
    to_call_val = _compute_to_call(gs, actor) if "call" in str_acts else 0

    for a in str_acts:
        if a in ("fold", "check"):
            result.append(LegalAction(action=a))
        elif a == "call":
            result.append(LegalAction(action="call", to_call=max(0, int(to_call_val or 0))))
        elif a in ("bet", "raise"):
            lo = max(1, bb)
            hi = actor_stack
            min_amt = _binary_search_min(gs, a, lo, hi)
            max_amt = _binary_search_max(gs, a, lo, hi)
            if min_amt is not None and max_amt is not None and min_amt <= max_amt:
                result.append(LegalAction(action=a, min=min_amt, max=max_amt))
        elif a == "allin":
            result.append(LegalAction(action="allin", min=actor_stack, max=actor_stack))
        else:
            # 忽略未知动作以避免策略误用
            pass

    return result


# 兼容旧签名：返回 List[str]（由引擎提供）
def legal_actions(gs) -> list[str]:
    return list(core_legal_actions(gs))
