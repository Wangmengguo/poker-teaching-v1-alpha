# tests/test_state_hu_minimal.py
from poker_core.state_hu import (
    apply_action,
    settle_if_needed,
    start_hand,
    start_session,
)


def test_one_hand_checkdown_showdown():
    cfg = start_session(init_stack=200)
    gs = start_hand(cfg, session_id="s1", hand_id="h1", button=0, seed=42)
    # preflop：SB 补齐到 BB，BB check 结束本街
    gs = apply_action(gs, "call")  # SB 补齐
    gs = apply_action(gs, "check")  # BB 关街
    # flop 循环两次 check
    gs = apply_action(gs, "check")
    gs = apply_action(gs, "check")
    # turn 同
    gs = apply_action(gs, "check")
    gs = apply_action(gs, "check")
    # river 同 → 进入 showdown
    gs = apply_action(gs, "check")
    gs = apply_action(gs, "check")
    gs = settle_if_needed(gs)
    assert gs.street == "complete"
    assert gs.players[0].stack + gs.players[1].stack == 400  # 筹码守恒


def test_short_call_refund_and_auto_advance():
    """测试短跟注退款和双方all-in自动推进"""
    cfg = start_session(init_stack=200)
    gs = start_hand(cfg, session_id="s1", hand_id="h2", button=0, seed=42)

    # 让玩家0下注一个大金额
    gs = apply_action(gs, "raise", amount=100)  # 玩家0加注到100
    assert gs.players[0].invested_street == 102  # 1(SB) + 1(to_call) + 100 = 102

    # 修改玩家1的可用筹码，让它只有50筹码
    from poker_core.state_hu import _replace_player, _update_player

    p1_new = _replace_player(gs.players[1], stack=50)  # 假设玩家1只有50筹码可用
    gs = _update_player(gs, 1, p1_new)

    # 玩家1 call，但筹码不足（to_call = max(102, 2) - 2 = 100，但只有50筹码）
    gs = apply_action(gs, "call")  # 玩家1尝试跟注，但只有50筹码

    # 验证退款逻辑和自动推进
    assert gs.players[1].all_in  # 玩家1应该all-in
    assert gs.players[1].stack == 0  # 玩家1筹码清零

    # 由于自动推进，invested_street已被重置为0，这里验证关键逻辑：
    # 1. 游戏自动推进到了showdown
    assert gs.street == "showdown"
    assert len(gs.board) == 5  # 翻牌+转牌+河牌

    # 2. 彩池应该包含了本街的投资（102 + 52 = 104）
    assert gs.pot == 104  # 本街投资102 + 52 = 104

    # 3. 玩家0应该收到退款（100 - 50 = 50）
    # 玩家0初始199，扣除加注101（1 to_call + 100），收到退款50，净结果：199 - 101 + 50 = 148
    assert gs.players[0].stack == 148

    # 结算并验证筹码守恒（含pot中的筹码）
    gs = settle_if_needed(gs)
    assert gs.street == "complete"
    total_chips = gs.players[0].stack + gs.players[1].stack
    # 注意：这里只验证玩家筹码之和，不包含pot，因为pot已分配给赢家
    assert total_chips == 252  # pot中的104筹码已分配给玩家1（赢家）
