from poker_core.state_hu import (
    BB,
    apply_action,
    legal_actions,
    settle_if_needed,
    start_hand,
    start_session,
)


def goto_flop(gs):
    # preflop：SB 补齐到 BB，BB check 进入翻牌
    gs = apply_action(gs, "call")
    gs = apply_action(gs, "check")
    assert gs.street == "flop"
    return gs


def test_preflop_close_after_sb_call_and_bb_check():
    cfg = start_session(init_stack=200)
    gs = start_hand(cfg, session_id="s1", hand_id="h1", button=0, seed=7)
    # SB 行动，可 call/raise；这里选择 call
    acts_sb = set(legal_actions(gs))
    assert "call" in acts_sb
    gs = apply_action(gs, "call")
    # 仅盲注对齐，轮到 BB，应允许：check 或 raise（但不应出现 bet）
    acts_bb = set(legal_actions(gs))
    assert "check" in acts_bb and "raise" in acts_bb and "bet" not in acts_bb
    gs = apply_action(gs, "check")
    assert gs.street == "flop"


def test_preflop_bb_can_raise_when_to_call_zero():
    cfg = start_session(init_stack=200)
    gs = start_hand(cfg, session_id="s1", hand_id="h2", button=0, seed=8)
    gs = apply_action(gs, "call")  # SB 补齐
    acts = set(legal_actions(gs))
    assert "raise" in acts and "bet" not in acts
    # BB 在 to_call=0 的情况下加注，最小加注增量为 BB
    gs = apply_action(gs, "raise", amount=BB)
    # 加注后 street 仍为 preflop，等待 SB 行动
    assert gs.street == "preflop"
    assert gs.to_act == 0  # SB 行动


def test_postflop_bet_call_immediately_advances():
    cfg = start_session(init_stack=200)
    gs = start_hand(cfg, session_id="s1", hand_id="h3", button=0, seed=9)
    gs = goto_flop(gs)
    # 翻牌圈未开火，OOP（非按钮）先手
    assert gs.to_act == 1
    gs = apply_action(gs, "bet", amount=BB)  # 开火下注
    # 对手 call 应立即推进到 turn
    gs = apply_action(gs, "call")
    assert gs.street == "turn"


def test_min_raise_short_allin_does_not_reopen_action():
    cfg = start_session(init_stack=200)
    gs = start_hand(cfg, session_id="s1", hand_id="h4", button=0, seed=10)
    gs = goto_flop(gs)
    # 非按钮先手，下注 10
    gs = apply_action(gs, "bet", amount=10)
    # 按规则，最小加注增量 = 上一次下注额 = 10
    # 按钮全下 12（对 to_call=10 为短加注，增量=2<10，不重开行动）
    gs = apply_action(gs, "allin")
    # 轮到非按钮，由于对手已全下，只能 fold/call，不允许 raise
    acts = set(legal_actions(gs))
    assert "raise" not in acts and "call" in acts and "fold" in acts


def test_both_allin_auto_deal_to_showdown_and_settle():
    cfg = start_session(init_stack=200)
    gs = start_hand(cfg, session_id="s1", hand_id="h5", button=0, seed=11)
    gs = goto_flop(gs)
    # 翻牌圈：非按钮下注 20，按钮全下 200，非按钮再全下跟注
    gs = apply_action(gs, "bet", amount=20)
    gs = apply_action(gs, "allin")  # 按钮推满
    # 轮到非按钮，若其也全下，双方 all-in(先手all-in，后手只能call/fold) 且对齐，自动发牌到摊牌
    gs = apply_action(gs, "call")
    # 自动推进应达到 showdown（未派彩）
    assert gs.street == "showdown" and len(gs.board) == 5
    # 结算派彩
    gs = settle_if_needed(gs)
    assert gs.street == "complete"
    assert gs.players[0].stack + gs.players[1].stack == 400


def test_unlimited_raises_multiple_times():
    cfg = start_session(init_stack=500)
    gs = start_hand(cfg, session_id="s1", hand_id="h6", button=0, seed=12)
    gs = goto_flop(gs)
    # 连续多次加注（不受 cap 限制）
    gs = apply_action(gs, "bet", amount=2)  # last_raise_size=2
    gs = apply_action(gs, "raise", amount=2)  # 1st raise，增量=2
    gs = apply_action(gs, "raise", amount=2)  # 2nd raise，增量=2
    gs = apply_action(gs, "raise", amount=2)  # 3rd raise，增量=2
    # 仍未到上限（无限注），下一手玩家应仍可选择 call 或继续加注
    acts = set(legal_actions(gs))
    assert "call" in acts


def test_opponent_allin_allows_only_call_or_fold():
    cfg = start_session(init_stack=200)
    gs = start_hand(cfg, session_id="s1", hand_id="h7", button=0, seed=13)
    # 直接进入翻牌圈，构造“对手开火式全下”的场景
    gs = apply_action(gs, "call")
    gs = apply_action(gs, "check")
    assert gs.street == "flop" and gs.to_act == 1  # 非按钮先手
    # 非按钮全下（作为开火下注），此时对手只能 call 或 fold，不能 raise/bet/check
    gs = apply_action(gs, "allin")
    acts = set(legal_actions(gs))
    assert acts == {"fold", "call"}
