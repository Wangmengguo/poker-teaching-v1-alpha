# tests/test_e2e_session_flow.py
import json

import pytest
from django.test import Client


def _post(c: Client, url: str, payload: dict):
    return c.post(url, data=json.dumps(payload), content_type="application/json")


def _get_json(c: Client, url: str):
    return c.get(url).json()


def _total_assets(hand_state: dict) -> int:
    """两侧栈 + 彩池 + 本街投资，总和应恒定（无抽水的简化不变量）"""
    players = hand_state.get("players", [])
    stacks = sum(int(p.get("stack", 0)) for p in players)
    pot = int(hand_state.get("pot", 0))
    bets = sum(int(p.get("bet", 0)) for p in players)
    return stacks + pot + bets


def _players_stacks(hand_state: dict):
    players = hand_state.get("players", [])
    return [int(players[0]["stack"]), int(players[1]["stack"])]


def _prefer_action(legal_actions):
    """尽量用 check / call 推进到摊牌，必要时再 fold"""
    la = set(legal_actions or [])
    if "check" in la:
        return {"action": "check"}
    if "call" in la:
        return {"action": "call"}
    if "fold" in la:
        return {"action": "fold"}
    # 极端情况兜底
    return {"action": list(la)[0]} if la else {"action": "check"}


@pytest.mark.django_db
def test_e2e_session_next_carry_rotate_counter_conserve():
    c = Client()

    # --- 1) 开局：自定义 sb/bb，便于验证贯穿 ---
    init_stack, sb, bb = 200, 5, 10
    s_resp = _post(
        c, "/api/v1/session/start", {"init_stack": init_stack, "sb": sb, "bb": bb}
    ).json()
    sid = s_resp["session_id"]

    # 对局状态（记下按钮与手数）
    ss_before = _get_json(c, f"/api/v1/session/{sid}/state")
    btn_before = int(ss_before["button"])
    hand_no_before = int(ss_before["hand_counter"])

    # --- 2) 开第一手 ---
    h1 = _post(c, "/api/v1/hand/start", {"session_id": sid, "seed": 42}).json()
    hid1 = h1["hand_id"]

    # 验证：开局 pot = 0，盲注在本街投资中
    body = _get_json(c, f"/api/v1/hand/state/{hid1}")
    st = body["state"]
    assert int(st["pot"]) == 0, "开手后彩池应为0"
    assert sum(int(p["bet"]) for p in st["players"]) == sb + bb, "开手后本街投资应等于 sb+bb"
    # 验证：筹码守恒（总资产 = 2*init_stack）
    base_total = _total_assets(st)
    assert base_total == 2 * init_stack

    # --- 2.5) 验证未结束时调用 /session/next 应返回 409 ---
    resp = _post(c, "/api/v1/session/next", {"session_id": sid})
    assert resp.status_code == 409, "未结束时调用 /session/next 应返回 409"

    # --- 3) 打完第一手（倾向 check/call 的“和平路线”）---
    for _ in range(80):
        body = _get_json(c, f"/api/v1/hand/state/{hid1}")
        st = body["state"]
        legal = body["legal_actions"]
        # 每步都守恒
        assert _total_assets(st) == base_total
        act = _prefer_action(legal)
        r = _post(c, f"/api/v1/hand/act/{hid1}", act).json()
        if r.get("hand_over"):  # 摊牌/弃牌结束
            break
    else:
        pytest.fail("第一手未在预期步数内结束")

    # 记录第一手结束时双方筹码
    body_end_1 = _get_json(c, f"/api/v1/hand/state/{hid1}")
    st_end_1 = body_end_1["state"]
    end_stacks = _players_stacks(st_end_1)
    assert _total_assets(st_end_1) == base_total  # 仍守恒

    # --- 4) 开下一手（按钮轮转 + 延续筹码）---
    nxt = _post(c, "/api/v1/session/next", {"session_id": sid}).json()
    assert "hand_id" in nxt
    hid2 = nxt["hand_id"]
    st2 = nxt["state"]  # 新手的快照
    assert st2.get("street") == "preflop"

    # 新手开始时 pot = 0，盲注在本街投资中
    assert int(st2["pot"]) == 0, "新手开始时彩池应为0"
    assert sum(int(p["bet"]) for p in st2["players"]) == sb + bb, "新手开始时本街投资应等于 sb+bb"

    # 按钮轮转：新手按钮应为 1 - btn_before
    btn_after = int(st2["button"])
    assert btn_after == 1 - btn_before

    # 手数 +1
    ss_after = _get_json(c, f"/api/v1/session/{sid}/state")
    assert int(ss_after["hand_counter"]) == hand_no_before + 1

    # 校验 session/state 盲注字段：sb、bb 应等于初始化值
    assert ss_after["sb"] == sb, "session state 的 sb 应等于初始化值"
    assert ss_after["bb"] == bb, "session state 的 bb 应等于初始化值"

    # 校验 current_hand_id：应等于新手 hand_id
    assert (
        ss_after["current_hand_id"] == hid2
    ), "session state 的 current_hand_id 应等于新手 hand_id"

    # 校验 stacks_after_blinds：应等于新手 state.players 的 stack
    assert ss_after["stacks_after_blinds"] == _players_stacks(
        st2
    ), "stacks_after_blinds 应等于新手两侧栈"

    # 校验 carry-over stacks：DB 中的 stacks 应等于第一手结束时的 end_stacks（承接栈为扣盲前）
    assert ss_after["stacks"] == end_stacks, "DB 中的 stacks 应等于第一手结束时的 end_stacks"

    # 延续筹码：新手开局后的玩家栈 = 第一手结束的栈 - （对应盲注）
    new_stacks = _players_stacks(st2)
    sb_index = btn_after  # 我们的规则：按钮位发 SB
    bb_index = 1 - btn_after

    assert end_stacks[sb_index] == new_stacks[sb_index] + sb, "SB 位应扣除 sb"
    assert end_stacks[bb_index] == new_stacks[bb_index] + bb, "BB 位应扣除 bb"

    # 跨手也要守恒：新手开局时（栈 + 彩池）仍等于基线总资产
    assert _total_assets(st2) == base_total, "跨手边界应保持筹码守恒"


@pytest.mark.django_db
def test_e2e_session_fold_early_end():
    """测试弃牌提前结束的路径，验证按钮轮转、筹码承接、守恒等规则"""
    c = Client()

    # --- 1) 开局：自定义 sb/bb ---
    init_stack, sb, bb = 200, 5, 10
    s_resp = _post(
        c, "/api/v1/session/start", {"init_stack": init_stack, "sb": sb, "bb": bb}
    ).json()
    sid = s_resp["session_id"]

    # 对局状态（记下按钮与手数）
    ss_before = _get_json(c, f"/api/v1/session/{sid}/state")
    btn_before = int(ss_before["button"])
    hand_no_before = int(ss_before["hand_counter"])

    # --- 2) 开第一手 ---
    h1 = _post(c, "/api/v1/hand/start", {"session_id": sid, "seed": 42}).json()
    hid1 = h1["hand_id"]

    # 验证：开局 pot = 0，盲注在本街投资中
    body = _get_json(c, f"/api/v1/hand/state/{hid1}")
    st = body["state"]
    assert int(st["pot"]) == 0, "开手后彩池应为0"
    assert sum(int(p["bet"]) for p in st["players"]) == sb + bb, "开手后本街投资应等于 sb+bb"
    base_total = _total_assets(st)
    assert base_total == 2 * init_stack

    # --- 3) 第一手快速弃牌结束 ---
    # 第一手：按钮位（SB）先行动，选择 fold
    body = _get_json(c, f"/api/v1/hand/state/{hid1}")
    st = body["state"]
    assert _total_assets(st) == base_total  # 守恒检查

    # 按钮位选择 fold
    act = {"action": "fold"}
    r = _post(c, f"/api/v1/hand/act/{hid1}", act).json()
    assert r.get("hand_over"), "弃牌后应结束"
    assert "outcome" in r, "应有 outcome"
    assert r["outcome"]["winner"] == 1 - btn_before, "非按钮位应获胜"

    # 记录第一手结束时双方筹码
    body_end_1 = _get_json(c, f"/api/v1/hand/state/{hid1}")
    st_end_1 = body_end_1["state"]
    end_stacks = _players_stacks(st_end_1)
    assert _total_assets(st_end_1) == base_total  # 仍守恒

    # --- 4) 开下一手（按钮轮转 + 延续筹码）---
    nxt = _post(c, "/api/v1/session/next", {"session_id": sid}).json()
    assert "hand_id" in nxt
    hid2 = nxt["hand_id"]
    st2 = nxt["state"]  # 新手的快照
    assert st2.get("street") == "preflop"

    # 新手开始时 pot = 0，盲注在本街投资中
    assert int(st2["pot"]) == 0, "新手开始时彩池应为0"
    assert sum(int(p["bet"]) for p in st2["players"]) == sb + bb, "新手开始时本街投资应等于 sb+bb"

    # 按钮轮转：新手按钮应为 1 - btn_before
    btn_after = int(st2["button"])
    assert btn_after == 1 - btn_before

    # 手数 +1
    ss_after = _get_json(c, f"/api/v1/session/{sid}/state")
    assert int(ss_after["hand_counter"]) == hand_no_before + 1

    # 校验 session/state 盲注字段：sb、bb 应等于初始化值
    assert ss_after["sb"] == sb, "session state 的 sb 应等于初始化值"
    assert ss_after["bb"] == bb, "session state 的 bb 应等于初始化值"

    # 校验 current_hand_id：应等于新手 hand_id
    assert (
        ss_after["current_hand_id"] == hid2
    ), "session state 的 current_hand_id 应等于新手 hand_id"

    # 校验 stacks_after_blinds：应等于新手 state.players 的 stack
    assert ss_after["stacks_after_blinds"] == _players_stacks(
        st2
    ), "stacks_after_blinds 应等于新手两侧栈"

    # 校验 carry-over stacks：DB 中的 stacks 应等于第一手结束时的 end_stacks（承接栈为扣盲前）
    assert ss_after["stacks"] == end_stacks, "DB 中的 stacks 应等于第一手结束时的 end_stacks"

    # 延续筹码：新手开局后的玩家栈 = 第一手结束的栈 - （对应盲注）
    new_stacks = _players_stacks(st2)
    sb_index = btn_after  # 我们的规则：按钮位发 SB
    bb_index = 1 - btn_after

    assert end_stacks[sb_index] == new_stacks[sb_index] + sb, "SB 位应扣除 sb"
    assert end_stacks[bb_index] == new_stacks[bb_index] + bb, "BB 位应扣除 bb"

    # 跨手也要守恒：新手开局时（栈 + 彩池）仍等于基线总资产
    assert _total_assets(st2) == base_total, "跨手边界应保持筹码守恒"


@pytest.mark.django_db
def test_e2e_session_carry_stacks_smaller_than_blinds_error():
    """测试承接栈小于盲注时的错误场景"""
    c = Client()

    # --- 1) 开局：设置较大的盲注 ---
    init_stack, sb, bb = 50, 20, 40  # 盲注很大，容易触发错误
    s_resp = _post(
        c, "/api/v1/session/start", {"init_stack": init_stack, "sb": sb, "bb": bb}
    ).json()
    sid = s_resp["session_id"]

    # --- 2) 开第一手 ---
    h1 = _post(c, "/api/v1/hand/start", {"session_id": sid, "seed": 42}).json()
    hid1 = h1["hand_id"]

    # --- 3) 第一手快速结束（让玩家筹码变得很少）---
    # 通过多次加注让玩家筹码减少
    for _ in range(10):
        body = _get_json(c, f"/api/v1/hand/state/{hid1}")
        legal = body["legal_actions"]

        if "raise" in legal:
            # 尽量加注，消耗筹码
            act = {"action": "raise", "amount": 10}
        elif "call" in legal:
            act = {"action": "call"}
        elif "check" in legal:
            act = {"action": "check"}
        elif "fold" in legal:
            act = {"action": "fold"}
        else:
            act = {"action": list(legal)[0]}

        r = _post(c, f"/api/v1/hand/act/{hid1}", act).json()
        if r.get("hand_over"):
            break

    # 记录第一手结束时双方筹码
    body_end_1 = _get_json(c, f"/api/v1/hand/state/{hid1}")
    st_end_1 = body_end_1["state"]
    end_stacks = _players_stacks(st_end_1)

    # 验证筹码确实变得很少（小于盲注）
    assert any(stack < min(sb, bb) for stack in end_stacks), "应该有玩家筹码小于盲注"

    # --- 4) 尝试开下一手，应该抛出错误 ---
    # 这里我们需要直接调用引擎层的 start_hand_with_carry 来测试错误
    from poker_core.state_hu import start_hand_with_carry

    # 模拟 session_next_api 的逻辑，但直接调用引擎函数
    cfg = {"init_stack": init_stack, "sb": sb, "bb": bb}
    session_id = sid
    hand_id = "test_hand"
    button = 0  # 假设按钮为0

    # 这里应该抛出 ValueError
    with pytest.raises(ValueError, match="carry stacks smaller than blinds"):
        start_hand_with_carry(
            cfg=cfg,
            session_id=session_id,
            hand_id=hand_id,
            button=button,
            stacks=tuple(end_stacks),  # 使用第一手结束时的筹码
            seed=42,
        )
