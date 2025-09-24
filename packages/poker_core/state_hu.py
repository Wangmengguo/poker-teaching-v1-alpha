# packages/poker_core/state_hu.py
from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Literal

from poker_core.cards import make_deck
from poker_core.providers.interfaces import Strength
from poker_core.providers.selector import get_evaluator
from poker_core.rng import RNG

SB = 1
BB = 2

Street = Literal["preflop", "flop", "turn", "river", "showdown", "complete"]


def _rng(seed: int | None) -> random.Random:
    rng = RNG(seed=seed)
    return rng.create()


def _shuffle(seed: int | None) -> list[str]:
    deck = make_deck()
    r = _rng(seed)
    r.shuffle(deck)
    return deck


@dataclass(frozen=True)
class Player:
    stack: int
    hole: list[str]  # len==2 once dealt
    invested_street: int = 0  # 本街已投入
    all_in: bool = False
    folded: bool = False


@dataclass(frozen=True)
class GameState:
    session_id: str
    hand_id: str
    button: int  # 0 或 1，表示谁是按钮（SB 一定是按钮）
    street: Street
    deck: list[str]
    board: list[str]
    players: tuple[Player, Player]  # 固定为座位顺序：seat0, seat1。角色由 button 推导
    sb: int
    bb: int
    pot: int
    to_act: int  # 当前行动者 index
    last_bet: int  # 本街最近一次投注额（用于 min raise 的简化）
    # 便于 UI/教学的事件流（可写可不写，先给上）
    events: list[dict]
    open_bet: bool
    checks_in_round: int
    last_raise_size: int = 0  # 上一次“加注的增量”（用于最小加注规则）


def start_session(init_stack: int = 200, sb: int = SB, bb: int = BB) -> dict:
    """返回对局配置（教学化，最小字典即可），真实对局对象我们不落库。"""
    return {
        "sb": sb,
        "bb": bb,
        "init_stack": init_stack,
    }


def start_hand(
    session_cfg: dict,
    session_id: str,
    hand_id: str,
    button: int,
    seed: int | None = None,
) -> GameState:
    """
    按 HU 规则：
    - players 固定为座位顺序（seat0, seat1）；由 `button` 推导当手的 SB/BB
    - SB=按钮，BB=非按钮；盲注直接从 stack 扣，并计入本街 invested_street
    - preflop 行动权在 按钮（SB） 手上；翻后行动权在非按钮手上
    """

    deck = _shuffle(seed)
    p0_hole = [deck[0], deck[2]]
    p1_hole = [deck[1], deck[3]]
    deck = deck[4:]
    init_stack = session_cfg["init_stack"]
    sb = int(session_cfg.get("sb", 1))
    bb = int(session_cfg.get("bb", 2))
    btn = button % 2

    # 固定按座位创建玩家，随后根据 button 决定谁贴盲
    if btn == 0:
        # seat0 为按钮/SB，seat1 为 BB
        p0 = Player(stack=init_stack - sb, hole=p0_hole, invested_street=sb)
        p1 = Player(stack=init_stack - bb, hole=p1_hole, invested_street=bb)
    else:
        # seat1 为按钮/SB，seat0 为 BB
        p0 = Player(stack=init_stack - bb, hole=p0_hole, invested_street=bb)
        p1 = Player(stack=init_stack - sb, hole=p1_hole, invested_street=sb)

    gs = GameState(
        session_id=session_id,
        hand_id=hand_id,
        button=btn,
        street="preflop",
        deck=deck,
        board=[],
        players=(p0, p1),
        pot=0,
        sb=sb,
        bb=bb,
        to_act=btn,  # HU 规则：preflop 由按钮（SB）先行动
        last_bet=bb,  # 视为当前最高注（BB），便于 min-raise 简化
        events=[],
        open_bet=True,
        checks_in_round=0,
        last_raise_size=bb,  # preflop 初始最小加注增量为 BB
    )
    # 依据按钮记录盲注事件（who 为座位 index）
    sb_idx, bb_idx = btn, 1 - btn
    gs.events.append({"t": "blind", "who": sb_idx, "amt": sb})
    gs.events.append({"t": "blind", "who": bb_idx, "amt": bb})
    gs.events.append({"t": "deal_hole", "p0": p0_hole, "p1": p1_hole})
    return gs


def _to_call(gs: GameState, actor: int) -> int:
    me = gs.players[actor]
    other = gs.players[1 - actor]
    # 当前街最大投资额：
    cur_max = max(me.invested_street, other.invested_street)
    return cur_max - me.invested_street


def legal_actions(gs: GameState) -> list[str]:
    if gs.street in ("showdown", "complete"):
        return []

    me = gs.players[gs.to_act]
    if me.folded or me.all_in:
        return []  # 理论上不会发生，防御

    to_call = _to_call(gs, gs.to_act)
    acts = []

    # 若对手已全下（HU 下无第三人），禁止任何进一步下注/加注
    other = gs.players[1 - gs.to_act]
    if other.all_in:
        if to_call == 0:
            # 状态应在上一个动作已自动推进；这里不应再有人行动
            return []
        else:
            return ["fold", "call"]

    if to_call == 0:
        acts.extend(["check"])
        if me.stack > 0:
            # 尚未开火：允许 bet（开火下注）
            if not gs.open_bet:
                acts.append("bet")
            # preflop 仅盲注对齐后，BB 可在 to_call==0 时选择加注
            if (
                gs.street == "preflop"
                and gs.open_bet
                and gs.last_bet == gs.bb
                and gs.to_act == (1 - gs.button)
            ):
                acts.append("raise")
            acts.append("allin")
    else:
        acts.append("fold")
        # 有钱才能 call/raise/allin
        if me.stack > 0:
            acts.append("call")
            if me.stack > to_call:
                acts.append("raise")
            acts.append("allin")

    return acts


def _replace_player(p: Player, **kw) -> Player:
    return replace(p, **kw)


def _update_player(gs: GameState, idx: int, newp: Player) -> GameState:
    lst = list(gs.players)
    lst[idx] = newp
    return replace(gs, players=tuple(lst))


def _street_first_to_act(gs: GameState) -> int:
    if gs.street == "preflop":
        return gs.button  # 按钮先手（HU 特例）
    else:
        return 1 - gs.button  # 翻后由非按钮先手


def _deal_board(gs: GameState, street: Street) -> GameState:
    deck = list(gs.deck)
    board = list(gs.board)
    if street == "flop":
        board += [deck.pop(0), deck.pop(0), deck.pop(0)]
    elif street == "turn":
        board += [deck.pop(0)]
    elif street == "river":
        board += [deck.pop(0)]
    return replace(gs, deck=deck, board=board)


def _reset_street(gs: GameState, next_street: Street) -> GameState:
    # 把本街投资加入彩池，清零 invested_street，重置加注次数与行动权
    p0, p1 = gs.players
    pot_add = p0.invested_street + p1.invested_street
    p0 = _replace_player(p0, invested_street=0)
    p1 = _replace_player(p1, invested_street=0)
    gs = replace(gs, players=(p0, p1), pot=gs.pot + pot_add, last_bet=0, last_raise_size=0)
    gs = replace(gs, street=next_street)
    if next_street in ("flop", "turn", "river"):
        gs = _deal_board(gs, next_street)
        gs.events.append({"t": "board", "street": next_street, "cards": list(gs.board)})
    return replace(gs, to_act=_street_first_to_act(gs))


def _both_satisfied(gs: GameState) -> bool:
    # 双方已对齐当前街注额，且最近一轮包含 check/check 或 bet/call
    p0, p1 = gs.players
    return p0.invested_street == p1.invested_street


def _maybe_advance_street(gs: GameState) -> GameState:
    if gs.street in ("showdown", "complete"):
        return gs

    def _advance(to: Street) -> GameState:
        new_gs = _reset_street(gs, to)
        # 进入新街时，回合状态清零
        return replace(new_gs, open_bet=False, checks_in_round=0)

    # 优先处理：任意一方 all-in 且已对齐 → 自动一路推进到摊牌
    # 说明：若仅一方 all-in，另一方仍有余筹，但由于对手已 all-in，
    #       根据 HU 规则对手无法再进行新一轮下注/加注；因此在对齐后
    #       应自动发完余下公共牌直至摊牌，避免“无人可行动”卡住。
    p0, p1 = gs.players
    if (p0.all_in and p1.all_in) or ((p0.all_in or p1.all_in) and _both_satisfied(gs)):
        cur = gs
        # 连续推进直至摊牌
        while True:
            if cur.street in ("preflop", "flop", "turn"):
                nxt = {"preflop": "flop", "flop": "turn", "turn": "river"}[cur.street]
                # 使用当前状态推进，保持 _advance 一致清理
                gs = cur
                cur = _reset_street(gs, nxt)
                cur = replace(cur, open_bet=False, checks_in_round=0)
                continue
            if cur.street == "river":
                gs = cur
                cur = _reset_street(gs, "showdown")
                cur = replace(cur, open_bet=False, checks_in_round=0)
                break
            break
        return cur

    if gs.street in ("preflop", "flop", "turn"):
        if gs.open_bet:
            if _both_satisfied(gs):
                nxt = {"preflop": "flop", "flop": "turn", "turn": "river"}[gs.street]
                # Preflop 特例处理：
                # - 若仅有盲注（last_bet == BB），SB 补齐后需要 BB 再 check 一次才关闭本街；
                # - 若已出现主动 bet/raise（last_bet > BB），则 call 后可立即进入下一街。
                if gs.street == "preflop":
                    if gs.last_bet > gs.bb:
                        return _advance(nxt)
                    if gs.checks_in_round >= 1:
                        return _advance(nxt)
                else:
                    return _advance(nxt)
        else:
            if gs.checks_in_round >= 2:
                nxt = {"preflop": "flop", "flop": "turn", "turn": "river"}[gs.street]
                return _advance(nxt)
    elif gs.street == "river":
        if gs.open_bet:
            if _both_satisfied(gs):
                # 进摊牌
                return _advance("showdown")
        else:
            if gs.checks_in_round >= 2:
                return _advance("showdown")
    return gs


def apply_action(gs: GameState, action: str, amount: int | None = None) -> GameState:
    """
    action ∈ {"check","fold","call","bet","raise","allin"}
    - bet/raise 需考虑最小额（简化：min = max(BB, to_call)）
    - allin 直接把可用筹码推入
    """
    actor = gs.to_act
    me = gs.players[actor]
    to_call = _to_call(gs, actor)

    if action not in legal_actions(gs):
        raise ValueError(f"illegal action: {action}")

    if action == "check":
        gs.events.append({"t": "check", "who": actor})
        # 交换行动者；若对齐则可能进下一街
        gs = replace(gs, checks_in_round=gs.checks_in_round + 1, to_act=1 - actor)
        return _maybe_advance_street(gs)

    if action == "fold":
        me = _replace_player(me, folded=True)
        gs = _update_player(gs, actor, me)
        gs.events.append({"t": "fold", "who": actor})
        # 直接结算到 complete（弃牌胜利）
        return _settle_fold(gs, winner=1 - actor)

    if action == "call":
        pay = min(me.stack, to_call)
        me = _replace_player(
            me,
            stack=me.stack - pay,
            invested_street=me.invested_street + pay,
            all_in=(me.stack - pay == 0),
        )
        gs = _update_player(gs, actor, me)

        # 若不足额跟注（pay < to_call），退还对手未被匹配的部分
        if pay < to_call:
            over = to_call - pay
            opp = gs.players[1 - actor]
            # 确保不退还超过对手已投资的金额（防御性编程）
            actual_refund = min(over, opp.invested_street)
            opp = _replace_player(
                opp,
                invested_street=opp.invested_street - actual_refund,
                stack=opp.stack + actual_refund,
            )
            gs = _update_player(gs, 1 - actor, opp)
            gs.events.append({"t": "call_short", "who": actor, "amt": pay, "refund": actual_refund})
            gs = replace(gs, to_act=1 - actor, open_bet=True, checks_in_round=0)
            return _maybe_advance_street(gs)

        # 精确跟注或常规跟注
        gs.events.append({"t": "call", "who": actor, "amt": pay})
        # call 保持本回合已有下注状态（open_bet 维持 True），并清空本轮 check 计数
        gs = replace(gs, to_act=1 - actor, open_bet=True, checks_in_round=0)
        return _maybe_advance_street(gs)

    if action == "bet":
        # 未有人主动下注/加注的场景（开火）
        assert to_call == 0
        if gs.open_bet:
            raise ValueError("cannot bet when betting already opened")
        min_bet = gs.bb
        bet = amount if amount is not None else min_bet
        bet = max(min_bet, bet)
        bet = min(bet, me.stack)  # all-in 也算 bet
        me = _replace_player(
            me,
            stack=me.stack - bet,
            invested_street=me.invested_street + bet,
            all_in=(me.stack - bet == 0),
        )
        gs = _update_player(gs, actor, me)
        gs.events.append({"t": "bet", "who": actor, "amt": bet})
        gs = replace(
            gs,
            last_bet=bet,
            last_raise_size=bet,
            to_act=1 - actor,
            open_bet=True,
            checks_in_round=0,
        )
        return gs

    if action == "raise":
        # 常规：已有下注/加注（to_call>0）；
        # 特例：preflop 仅盲注对齐后（open_bet=True 且 last_bet==BB）且轮到 BB，to_call==0 也允许加注。
        preflop_blind_raise = (
            gs.street == "preflop"
            and gs.open_bet
            and gs.last_bet == gs.bb
            and to_call == 0
            and actor == (1 - gs.button)
        )
        if not preflop_blind_raise:
            assert to_call > 0
        # 最小加注“增量”
        min_inc = max(1, gs.last_raise_size)
        req_add = amount if amount is not None else min_inc
        req_add = max(min_inc, req_add)
        # 可用最大增量（受筹码限制）
        max_add = me.stack if preflop_blind_raise else max(0, me.stack - to_call)
        actual_add = min(req_add, max_add)
        if preflop_blind_raise:
            total_put = actual_add
        else:
            total_put = to_call + actual_add
        me = _replace_player(
            me,
            stack=me.stack - total_put,
            invested_street=me.invested_street + total_put,
            all_in=(me.stack - total_put == 0),
        )
        gs = _update_player(gs, actor, me)
        gs.events.append({"t": "raise", "who": actor, "to": me.invested_street})
        # 若实际加注未达到最小增量，则按“跟注/不足额加注”处理：不更新 last_bet/last_raise_size（不重开行动）
        if actual_add >= min_inc:
            gs = replace(
                gs,
                last_bet=gs.last_bet + actual_add,
                last_raise_size=actual_add,
                to_act=1 - actor,
                open_bet=True,
                checks_in_round=0,
            )
        else:
            gs = replace(gs, to_act=1 - actor, open_bet=True, checks_in_round=0)
        return gs

    if action == "allin":
        push = me.stack
        if push <= 0:
            raise ValueError("cannot all-in with zero")
        # 根据场景将 all-in 解释为 bet / raise / call
        if to_call == 0:
            if not gs.open_bet:
                # 作为开火下注
                me = _replace_player(
                    me, stack=0, invested_street=me.invested_street + push, all_in=True
                )
                gs = _update_player(gs, actor, me)
                gs.events.append({"t": "allin", "who": actor, "amt": push, "as": "bet"})
                gs = replace(
                    gs,
                    last_bet=push,
                    last_raise_size=push,
                    to_act=1 - actor,
                    open_bet=True,
                    checks_in_round=0,
                )
                return gs
            # preflop 仅盲注对齐时 BB 的 all-in 视为 raise（需达到最小加注增量）
            preflop_blind_raise = (
                gs.street == "preflop"
                and gs.open_bet
                and gs.last_bet == gs.bb
                and actor == (1 - gs.button)
            )
            if preflop_blind_raise:
                min_inc = max(1, gs.last_raise_size)
                actual_add = push
                me = _replace_player(
                    me, stack=0, invested_street=me.invested_street + push, all_in=True
                )
                gs = _update_player(gs, actor, me)
                gs.events.append({"t": "allin", "who": actor, "amt": push, "as": "raise"})
                if actual_add >= min_inc:
                    gs = replace(
                        gs,
                        last_bet=gs.last_bet + actual_add,
                        last_raise_size=actual_add,
                    )
                gs = replace(gs, to_act=1 - actor, open_bet=True, checks_in_round=0)
                return gs
            # 其他 to_call==0 且已开火的情形：不可 all-in 加注（HU 对手必须能响应）。视为非法
            raise ValueError("cannot all-in without open bet or blind-raise option")
        else:
            # 面对下注：all-in 可能是跟注或（达到最小增量的）加注
            pay = min(push, to_call)
            remaining = push - pay
            # 更新自己为 all-in
            me = _replace_player(
                me, stack=0, invested_street=me.invested_street + push, all_in=True
            )
            gs = _update_player(gs, actor, me)
            # 若不足额跟注（pay < to_call），退还对手未被匹配的部分
            if pay < to_call:
                over = to_call - pay
                opp = gs.players[1 - actor]
                opp = _replace_player(
                    opp,
                    invested_street=opp.invested_street - over,
                    stack=opp.stack + over,
                )
                gs = _update_player(gs, 1 - actor, opp)
                gs.events.append(
                    {
                        "t": "allin",
                        "who": actor,
                        "amt": push,
                        "as": "call_short",
                        "refund": over,
                    }
                )
                gs = replace(gs, to_act=1 - actor, open_bet=True, checks_in_round=0)
                return _maybe_advance_street(gs)
            # 精确跟注（push == to_call）
            if remaining == 0:
                gs.events.append({"t": "allin", "who": actor, "amt": push, "as": "call"})
                gs = replace(gs, to_act=1 - actor, open_bet=True, checks_in_round=0)
                return _maybe_advance_street(gs)
            # 超额部分视为加注增量
            min_inc = max(1, gs.last_raise_size)
            actual_add = remaining
            gs.events.append({"t": "allin", "who": actor, "amt": push, "as": "raise"})
            if actual_add >= min_inc:
                gs = replace(gs, last_bet=gs.last_bet + actual_add, last_raise_size=actual_add)
            gs = replace(gs, to_act=1 - actor, open_bet=True, checks_in_round=0)
            return _maybe_advance_street(gs)

    raise RuntimeError("unreachable")


def _hand_strength(cards7: list[str]) -> Strength:
    # 使用 providers 适配层：优先调用 pokerkit，否则回退到简化强度
    hole, board = cards7[:2], cards7[2:]
    return get_evaluator().evaluate7(hole, board).strength


def _settle_fold(gs: GameState, winner: int) -> GameState:
    # 把当前街筹码与彩池清算给赢家
    p0, p1 = gs.players
    pot_total = gs.pot + p0.invested_street + p1.invested_street
    # 胜者收锅
    if winner == 0:
        p0 = _replace_player(p0, stack=p0.stack + pot_total, invested_street=0)
        p1 = _replace_player(p1, invested_street=0)
    else:
        p1 = _replace_player(p1, stack=p1.stack + pot_total, invested_street=0)
        p0 = _replace_player(p0, invested_street=0)
    gs = replace(gs, players=(p0, p1), pot=0, street="complete", to_act=-1)
    gs.events.append({"t": "win_fold", "who": winner, "amt": pot_total})
    return gs


def _showdown_eval(gs: GameState) -> tuple[int | None, bool, list[list[str]]]:
    # 返回 (winner_index or None for tie, is_tie, [hole_cards_for_each_player])
    ev = get_evaluator()
    p0, p1 = gs.players
    r0 = ev.evaluate7(p0.hole, gs.board)
    r1 = ev.evaluate7(p1.hole, gs.board)
    s0, s1 = r0.strength, r1.strength
    if s0 > s1:
        return (0, False, [r0.best5, r1.best5])
    if s1 > s0:
        return (1, False, [r1.best5, r0.best5])
    return (None, True, [r0.best5, r1.best5])


def settle_if_needed(gs: GameState) -> GameState:
    # 在 river 对齐后会进入 "showdown"；这里完成摊牌并派彩
    if gs.street != "showdown":
        return gs
    # 把最后一街的投资并入彩池
    p0, p1 = gs.players
    pot_total = gs.pot + p0.invested_street + p1.invested_street
    p0 = _replace_player(p0, invested_street=0)
    p1 = _replace_player(p1, invested_street=0)
    gs = replace(gs, pot=0, players=(p0, p1))

    winner, tie, best5 = _showdown_eval(gs)
    gs.events.append(
        {
            "t": "showdown",
            "winner": winner,
            "is_tie": tie,
            "best5": best5,
            "board": list(gs.board),
        }
    )

    if tie:
        p0 = _replace_player(gs.players[0], stack=gs.players[0].stack + pot_total // 2)
        p1 = _replace_player(gs.players[1], stack=gs.players[1].stack + pot_total - pot_total // 2)
        gs = replace(gs, players=(p0, p1))
        gs.events.append({"t": "split", "amt": pot_total})
    else:
        pw = gs.players[winner]
        pw = _replace_player(pw, stack=pw.stack + pot_total)
        lst = list(gs.players)
        lst[winner] = pw
        gs = replace(gs, players=tuple(lst))
        gs.events.append({"t": "win_showdown", "who": winner, "amt": pot_total})

    return replace(gs, street="complete", to_act=-1)


def start_hand_with_carry(
    cfg,
    session_id: str,
    hand_id: str,
    button: int,
    stacks: tuple[int, int],
    seed: int | None = None,
):
    """
    在沿用上一手 stacks 的前提下开新手。
    - 不改变原 start_hand 的签名/行为，避免破坏现有调用点。
    """
    gs = start_hand(cfg, session_id=session_id, hand_id=hand_id, button=button, seed=seed)
    # 用上一手后的筹码覆盖刚开局的玩家堆栈
    inv0 = gs.players[0].invested_street  # 本手 start_hand 已写入的 SB/BB
    inv1 = gs.players[1].invested_street
    s0, s1 = stacks
    if s0 < inv0 or s1 < inv1:
        raise ValueError("carry stacks smaller than blinds; unsupported in MVP")
    p0 = replace(gs.players[0], stack=s0 - inv0)
    p1 = replace(gs.players[1], stack=s1 - inv1)
    gs = replace(gs, players=(p0, p1))
    return gs
