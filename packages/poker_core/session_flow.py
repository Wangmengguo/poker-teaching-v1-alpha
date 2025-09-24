# packages/poker_core/session_flow.py
from __future__ import annotations

from poker_core.session_types import NextHandPlan, SessionView


def next_hand(session: SessionView, last_gs, seed: int | None = None) -> NextHandPlan:
    """
    基于 “对局会话视图 + 上一手已complete的gs” 规划下一手：
    - 按会话规则轮转按钮
    - 沿用上一手后的 stacks
    - 手数 +1
    - 透传 seed
    """
    assert getattr(last_gs, "street", None) == "complete", "last hand not complete"
    next_button = 1 - session.button
    # 由上一手结算后的 gs 抽取新起点堆栈
    stacks = (last_gs.players[0].stack, last_gs.players[1].stack)
    return NextHandPlan(
        session_id=session.session_id,
        next_button=next_button,
        stacks=stacks,
        next_hand_no=session.hand_no + 1,
        seed=seed,
    )
