import json

import pytest
from django.test import Client


def _post(c: Client, url: str, payload: dict):
    return c.post(url, data=json.dumps(payload), content_type="application/json")


def _start_session_and_hand(c: Client, init_stack=200, sb=1, bb=2, seed=42):
    s = _post(c, "/api/v1/session/start", {"init_stack": init_stack, "sb": sb, "bb": bb}).json()
    sid = s["session_id"]
    h = _post(c, "/api/v1/hand/start", {"session_id": sid, "seed": seed}).json()
    hid = h["hand_id"]
    return sid, hid


@pytest.mark.django_db
def test_suggest_ok_returns_legal_action(client: Client):
    sid, hid = _start_session_and_hand(client, sb=2, bb=4, seed=7)

    # 查询当前行动者与合法动作
    st = client.get(f"/api/v1/hand/state/{hid}").json()
    to_act = int(st["state"]["to_act"])  # 0 or 1
    legal = set(st["legal_actions"]) or set()

    r = _post(client, "/api/v1/suggest", {"hand_id": hid, "actor": to_act})
    assert r.status_code == 200, r.content
    body = r.json()

    # 响应结构校验
    assert body.get("hand_id") == hid
    assert body.get("actor") == to_act
    assert isinstance(body.get("suggested"), dict)
    action = body["suggested"].get("action")
    amount = body["suggested"].get("amount", None)
    assert action in {"fold", "check", "call", "bet", "raise"}
    # 必须在当前合法动作集合内
    assert (
        (action in legal)
        or (action == "bet" and "bet" in legal)
        or (action == "raise" and "raise" in legal)
    )
    if amount is not None:
        assert isinstance(amount, int) and amount >= 1


@pytest.mark.django_db
def test_suggest_409_not_actors_turn(client: Client):
    sid, hid = _start_session_and_hand(client, seed=13)
    st = client.get(f"/api/v1/hand/state/{hid}").json()
    to_act = int(st["state"]["to_act"])  # 0 or 1
    not_actor = 1 - to_act
    r = _post(client, "/api/v1/suggest", {"hand_id": hid, "actor": not_actor})
    assert r.status_code == 409
    assert "detail" in r.json()


@pytest.mark.django_db
def test_suggest_409_when_hand_already_ended(client: Client):
    sid, hid = _start_session_and_hand(client, seed=17)
    # 走到结束（最多 40 步防止死循环）
    for _ in range(40):
        st = client.get(f"/api/v1/hand/state/{hid}").json()
        la = st["legal_actions"] or ["check"]
        resp = _post(client, f"/api/v1/hand/act/{hid}", {"action": la[0]}).json()
        if resp.get("hand_over"):
            break
    # 结束后再请求 suggest
    r = _post(client, "/api/v1/suggest", {"hand_id": hid, "actor": 0})
    assert r.status_code == 409
    assert "detail" in r.json()


@pytest.mark.django_db
def test_suggest_404_when_hand_not_found(client: Client):
    r = _post(client, "/api/v1/suggest", {"hand_id": "not_exist", "actor": 0})
    assert r.status_code == 404
    assert "detail" in r.json()
