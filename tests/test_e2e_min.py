# tests/test_e2e_min.py
from poker_core.state_hu import (
    apply_action,
    settle_if_needed,
    start_hand,
    start_session,
)


def total(gs):
    # 正确计算：玩家筹码 + 底池 + 当前街投资
    return (
        gs.players[0].stack
        + gs.players[1].stack
        + gs.pot
        + gs.players[0].invested_street
        + gs.players[1].invested_street
    )


def apply_and_check(gs, action, amount=None, total0=None):
    if total0 is None:
        total0 = total(gs)
    gs = apply_action(gs, action, amount)
    assert total(gs) == total0
    return gs, total0


def test_e2e_fold_finishes_and_conserves():
    cfg = start_session(init_stack=200)  # 两边各200，共400
    gs = start_hand(cfg, session_id="s1", hand_id="h1", button=0, seed=42)
    total0 = total(gs)
    gs, total0 = apply_and_check(gs, "raise", 4, total0)
    gs, total0 = apply_and_check(gs, "fold", None, total0)
    gs = settle_if_needed(gs)
    # 结束：底池清零，筹码回到赢家
    assert gs.street == "complete" and gs.pot == 0
    assert total(gs) == total0


def test_e2e_checkdown_showdown():
    cfg = start_session(init_stack=200)
    gs = start_hand(cfg, session_id="s1", hand_id="h2", button=0, seed=43)
    total0 = total(gs)
    # 走到 showdown（根据你当前合法动作推进）
    for a in ["call", "check", "check", "check", "check", "check", "check", "check"]:
        gs, total0 = apply_and_check(gs, a, None, total0)
    gs = settle_if_needed(gs)
    assert gs.street == "complete" and gs.pot == 0
    # 赢家/最佳五张应已在回放或 outcome 中可取（视你的实现断言）
