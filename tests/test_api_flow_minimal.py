import json

import pytest
from django.test import Client


@pytest.mark.django_db
def test_minimal_flow():
    c = Client()
    r = c.post("/api/v1/session/start", data=json.dumps({}), content_type="application/json")
    assert r.status_code == 200
    sid = r.json()["session_id"]

    r = c.post(
        "/api/v1/hand/start",
        data=json.dumps({"session_id": sid}),
        content_type="application/json",
    )
    assert r.status_code == 200
    hid = r.json()["hand_id"]

    # 取一次 state
    r = c.get(f"/api/v1/hand/state/{hid}")
    body = r.json()
    assert "legal_actions" in body and isinstance(body["legal_actions"], list)

    # 走一个动作（按返回的 legal_actions 选一个）
    act = body["legal_actions"][0] if body["legal_actions"] else "check"
    r = c.post(
        f"/api/v1/hand/act/{hid}",
        data=json.dumps({"action": act}),
        content_type="application/json",
    )
    assert r.status_code == 200
    assert "state" in r.json()


@pytest.mark.django_db
def test_act_returns_outcome_when_hand_over(client):
    # 1) start session
    sid = client.post("/api/v1/session/start", data="{}", content_type="application/json").json()[
        "session_id"
    ]
    # 2) start hand with fixed seed
    hid = client.post(
        "/api/v1/hand/start",
        data=json.dumps({"session_id": sid, "seed": 42}),
        content_type="application/json",
    ).json()["hand_id"]
    # 3) 走到结束（这里随便打一通，或调用你已有的帮助函数）
    #    为简单起见：循环最多 30 步，遇到 hand_over 就断
    for _ in range(30):
        body = client.get(f"/api/v1/hand/state/{hid}").json()
        la = body["legal_actions"] or ["check"]
        r = client.post(
            f"/api/v1/hand/act/{hid}",
            data=json.dumps({"action": la[0]}),
            content_type="application/json",
        ).json()
        if r["hand_over"]:
            assert "outcome" in r
            assert set(r["outcome"].keys()) == {"winner", "best5"}
            break


@pytest.mark.django_db
def test_replay_has_winner_and_best5(client):
    """测试重放数据包含完整的winner和best5信息，验证统一数据结构"""

    # 1) 创建会话并开始手牌
    sid = client.post("/api/v1/session/start", data="{}", content_type="application/json").json()[
        "session_id"
    ]
    hid = client.post(
        "/api/v1/hand/start",
        data=json.dumps({"session_id": sid, "seed": 42}),
        content_type="application/json",
    ).json()["hand_id"]

    # 2) 完成游戏流程直到结束
    game_over = False
    for _ in range(30):  # 最多30步防止无限循环
        state_body = client.get(f"/api/v1/hand/state/{hid}").json()
        legal_actions = state_body["legal_actions"] or ["check"]

        # 执行动作
        act_response = client.post(
            f"/api/v1/hand/act/{hid}",
            data=json.dumps({"action": legal_actions[0]}),
            content_type="application/json",
        ).json()

        if act_response["hand_over"]:
            game_over = True
            break

    # 确保游戏确实结束了
    assert game_over, "Game should have ended within 30 steps"

    # 3) 获取重放数据
    replay_response = client.get(f"/api/v1/replay/{hid}")
    assert (
        replay_response.status_code == 200
    ), f"Replay API should return 200, got {replay_response.status_code}"

    replay_data = replay_response.json()

    # 4) 验证统一数据结构 - 基本信息
    assert "hand_id" in replay_data, "Replay should contain hand_id"
    assert replay_data["hand_id"] == hid, "Hand ID should match"
    assert "session_id" in replay_data, "Replay should contain session_id"
    assert "seed" in replay_data, "Replay should contain seed"
    assert replay_data["seed"] == 42, "Seed should match the one used"

    # 5) 验证游戏数据
    assert "events" in replay_data, "Replay should contain events"
    assert "board" in replay_data, "Replay should contain board"
    assert "winner" in replay_data, "Replay should contain winner"
    assert "best5" in replay_data, "Replay should contain best5"

    # 6) 验证教学数据
    assert "players" in replay_data, "Replay should contain players"
    assert "annotations" in replay_data, "Replay should contain annotations"

    # 7) 验证元数据
    assert "engine_commit" in replay_data, "Replay should contain engine_commit"
    assert "schema_version" in replay_data, "Replay should contain schema_version"
    assert "created_at" in replay_data, "Replay should contain created_at"

    # 8) 验证winner格式 (应该是0, 1, 或None for tie)
    winner = replay_data["winner"]
    assert winner is None or winner in [
        0,
        1,
    ], f"Winner should be None, 0, or 1, got {winner}"

    # 9) 验证best5格式
    best5 = replay_data["best5"]
    if best5 is not None:  # 摊牌情况
        assert isinstance(best5, list), "best5 should be a list when not None"
        assert len(best5) == 2, f"best5 should contain 2 hands, got {len(best5)}"

        for i, hand in enumerate(best5):
            assert isinstance(hand, list), f"Hand {i} should be a list"
            assert len(hand) == 5, f"Hand {i} should contain 5 cards, got {len(hand)}"

            # 验证每张牌的格式 (如 "As", "Kh")
            for j, card in enumerate(hand):
                assert isinstance(card, str), f"Card {j} in hand {i} should be string"
                assert len(card) == 2, f"Card {j} in hand {i} should be 2 characters, got '{card}'"
    # else: best5是None表示弃牌结束，这也是合法的

    # 10) 验证events不为空(应该至少有发牌和盲注事件)
    events = replay_data["events"]
    assert isinstance(events, list), "Events should be a list"
    assert len(events) > 0, "Events should not be empty"

    # 11) 验证players数据
    players = replay_data["players"]
    if players is not None:
        assert isinstance(players, list), "Players should be a list"
        assert len(players) == 2, f"Should have 2 players, got {len(players)}"

    # 12) 验证steps数据 - 修复后不应该为None
    steps = replay_data["steps"]
    assert steps is not None, "Steps should not be None after fix"
    assert isinstance(steps, list), "Steps should be a list"
    assert len(steps) > 0, "Steps should not be empty"

    # 验证steps结构
    first_step = steps[0]
    assert "idx" in first_step, "Each step should have idx"
    assert "evt" in first_step, "Each step should have evt"
    assert "payload" in first_step, "Each step should have payload"

    # 验证包含关键事件
    events = [step["evt"] for step in steps]
    assert "GAME_START" in events, "Should contain GAME_START event"
