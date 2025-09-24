import json

import pytest
from django.test import Client


def _post(c: Client, url: str, payload: dict):
    return c.post(url, data=json.dumps(payload), content_type="application/json")


@pytest.mark.django_db
def test_ui_game_page_and_act_flow():
    c = Client()
    # 准备：创建会话与手牌
    sid = _post(c, "/api/v1/session/start", {}).json()["session_id"]
    hid = _post(c, "/api/v1/hand/start", {"session_id": sid, "seed": 7}).json()["hand_id"]

    # 访问 UI 页面
    r = c.get(f"/api/v1/ui/game/{sid}/{hid}")
    assert r.status_code == 200
    assert b"action-form" in r.content

    # 获取一次 state，选择一个合法动作
    st = c.get(f"/api/v1/hand/state/{hid}").json()
    legal = st.get("legal_actions") or ["check"]
    action = legal[0]

    # 走 UI 粘合端点
    r2 = c.post(f"/api/v1/ui/hand/{hid}/act", data={"action": action})
    assert r2.status_code == 200
    # OOB 片段中应包含 legal-actions/amount-wrap 的容器
    text = r2.content.decode("utf-8")
    assert 'id="legal-actions"' in text
    assert 'id="amount-wrap"' in text


@pytest.mark.django_db
def test_ui_coach_suggest_returns_panel():
    c = Client()
    sid = _post(c, "/api/v1/session/start", {}).json()["session_id"]
    hid = _post(c, "/api/v1/hand/start", {"session_id": sid, "seed": 11}).json()["hand_id"]
    # 轮到谁
    st = c.get(f"/api/v1/hand/state/{hid}").json()
    actor = int(st["state"]["to_act"]) if st.get("state") else 0
    r = c.post(f"/api/v1/ui/coach/{hid}/suggest", data={"hand_id": hid, "actor": actor})
    assert r.status_code == 200
    assert b'id="coach-panel"' in r.content


@pytest.mark.django_db
def test_ui_start_redirect_and_game_includes_seats_and_log():
    c = Client()
    # GET start page renders splash
    r0 = c.get("/api/v1/ui/start")
    assert r0.status_code == 200
    # POST start should create session+hand and return HX-Redirect
    r1 = c.post("/api/v1/ui/start")
    assert r1.status_code == 200
    assert "HX-Redirect" in r1, "ui/start POST should set HX-Redirect"
    goto = r1["HX-Redirect"]
    assert goto.startswith("/api/v1/ui/game/")
    # Game page should include board, seats and action log containers
    r2 = c.get(goto)
    html = r2.content.decode("utf-8")
    assert 'id="board"' in html
    assert 'id="seats"' in html
    assert 'id="action-log"' in html
    assert 'id="action-form"' in html


def _prefer_action(legal):
    la = set(legal or [])
    if "check" in la:
        return {"action": "check"}
    if "call" in la:
        return {"action": "call"}
    if "fold" in la:
        return {"action": "fold"}
    return {"action": list(la)[0]} if la else {"action": "check"}


@pytest.mark.django_db
def test_ui_act_oob_updates_board_seats_and_log():
    c = Client()
    # Prepare a session and a hand
    sid = _post(c, "/api/v1/session/start", {}).json()["session_id"]
    hid = _post(c, "/api/v1/hand/start", {"session_id": sid, "seed": 7}).json()["hand_id"]

    # Perform one UI action via glue endpoint
    st = c.get(f"/api/v1/hand/state/{hid}").json()
    action = _prefer_action(st.get("legal_actions"))
    r = c.post(f"/api/v1/ui/hand/{hid}/act", data=action)
    assert r.status_code == 200
    txt = r.content.decode("utf-8")
    # OOB fragments should include these containers for live update
    assert 'id="board"' in txt
    assert 'id="seats"' in txt
    assert 'id="action-log"' in txt


@pytest.mark.django_db
def test_ui_session_next_sets_push_url_and_updates_fragments():
    c = Client()
    # Start session/hand
    sid = _post(c, "/api/v1/session/start", {}).json()["session_id"]
    hid = _post(c, "/api/v1/hand/start", {"session_id": sid, "seed": 11}).json()["hand_id"]

    # Play the hand to completion using REST to keep it short
    for _ in range(120):
        body = c.get(f"/api/v1/hand/state/{hid}").json()
        if body.get("state", {}).get("street") == "complete":
            break
        act = _prefer_action(body.get("legal_actions"))
        res = _post(c, f"/api/v1/hand/act/{hid}", act).json()
        if res.get("hand_over"):
            break
    # Call UI next; should set HX-Push-Url and include OOB fragments
    r = c.post(f"/api/v1/ui/session/{sid}/next")
    assert r.status_code == 200
    assert "HX-Push-Url" in r, "ui/session/next should set HX-Push-Url"
    s = r.content.decode("utf-8")
    assert 'id="action-form"' in s
    assert 'id="seats"' in s
    assert 'id="board"' in s


@pytest.mark.django_db
def test_session_end_by_max_hands_and_idempotent():
    c = Client()
    # Create session with max_hands=1 so next ends immediately after first hand
    sid = _post(c, "/api/v1/session/start", {"max_hands": 1}).json()["session_id"]
    # Start first hand and complete quickly
    hid = _post(c, "/api/v1/hand/start", {"session_id": sid, "seed": 3}).json()["hand_id"]
    for _ in range(80):
        st = c.get(f"/api/v1/hand/state/{hid}").json()
        if st.get("state", {}).get("street") == "complete":
            break
        act = _prefer_action(st.get("legal_actions"))
        r = _post(c, f"/api/v1/hand/act/{hid}", act).json()
        if r.get("hand_over"):
            break
    # REST session/next should return 409 with summary
    r1 = _post(c, "/api/v1/session/next", {"session_id": sid})
    assert r1.status_code == 409
    body1 = r1.json()
    assert body1.get("ended_reason") == "max_hands"
    assert "final_stacks" in body1 and "pnl" in body1 and "hands_played" in body1
    # UI session/next should return 200 with end card (no Push-Url)
    r2 = c.post(f"/api/v1/ui/session/{sid}/next")
    assert r2.status_code == 200
    assert "HX-Push-Url" not in r2
    html2 = r2.content.decode("utf-8")
    assert "Session Ended" in html2 and 'id="action-form"' in html2
    # Idempotent: repeat both; results should be consistent
    r3 = _post(c, "/api/v1/session/next", {"session_id": sid})
    assert r3.status_code == 409
    assert r3.json() == body1
    r4 = c.post(f"/api/v1/ui/session/{sid}/next")
    assert r4.status_code == 200
    assert "HX-Push-Url" not in r4
    assert "Session Ended" in r4.content.decode("utf-8")


@pytest.mark.django_db
def test_session_end_by_bust_ui_and_rest():
    c = Client()
    # Large blinds to make bust likely on next hand
    s_resp = _post(c, "/api/v1/session/start", {"init_stack": 50, "sb": 20, "bb": 40}).json()
    sid = s_resp["session_id"]
    hid = _post(c, "/api/v1/hand/start", {"session_id": sid, "seed": 42}).json()["hand_id"]
    # Drive to all-in quickly
    for _ in range(40):
        st = c.get(f"/api/v1/hand/state/{hid}").json()
        if st.get("state", {}).get("street") == "complete":
            break
        la = st.get("legal_actions") or []
        if "allin" in la:
            act = {"action": "allin"}
        elif "raise" in la:
            act = {"action": "raise", "amount": 40}
        elif "bet" in la:
            act = {"action": "bet", "amount": 40}
        elif "call" in la:
            act = {"action": "call"}
        elif "check" in la:
            act = {"action": "check"}
        else:
            act = {"action": la[0]}
        r = _post(c, f"/api/v1/hand/act/{hid}", act).json()
        if r.get("hand_over"):
            break
    # REST next should 409 bust summary
    r1 = _post(c, "/api/v1/session/next", {"session_id": sid})
    assert r1.status_code == 409
    b1 = r1.json()
    assert b1.get("ended_reason") in {"bust", "max_hands"}  # primarily bust expected
    # UI next should OOB end card and no push url
    r2 = c.post(f"/api/v1/ui/session/{sid}/next")
    assert r2.status_code == 200
    assert "HX-Push-Url" not in r2
    assert "Session Ended" in r2.content.decode("utf-8")


@pytest.mark.django_db
def test_ui_game_ssr_shows_end_card_when_session_ended():
    c = Client()
    sid = _post(c, "/api/v1/session/start", {"max_hands": 1}).json()["session_id"]
    hid = _post(c, "/api/v1/hand/start", {"session_id": sid, "seed": 1}).json()["hand_id"]
    # Finish the hand
    for _ in range(60):
        st = c.get(f"/api/v1/hand/state/{hid}").json()
        if st.get("state", {}).get("street") == "complete":
            break
        act = _prefer_action(st.get("legal_actions"))
        r = _post(c, f"/api/v1/hand/act/{hid}", act).json()
        if r.get("hand_over"):
            break
    # End via REST (max_hands)
    _ = _post(c, "/api/v1/session/next", {"session_id": sid})
    # SSR: game page should show end card and no action form posting
    page = c.get(f"/api/v1/ui/game/{sid}/{hid}").content.decode("utf-8")
    assert "Session Ended" in page
    assert "/api/v1/ui/hand/" not in page  # no action form


@pytest.mark.django_db
def test_ui_replay_page_minimal():
    c = Client()
    # Create and finish a hand to persist replay
    sid = _post(c, "/api/v1/session/start", {}).json()["session_id"]
    hid = _post(c, "/api/v1/hand/start", {"session_id": sid, "seed": 9}).json()["hand_id"]
    for _ in range(100):
        st = c.get(f"/api/v1/hand/state/{hid}").json()
        if st.get("state", {}).get("street") == "complete":
            break
        act = _prefer_action(st.get("legal_actions"))
        r = _post(c, f"/api/v1/hand/act/{hid}", act).json()
        if r.get("hand_over"):
            break
    # Load replay UI
    r = c.get(f"/api/v1/ui/replay/{hid}")
    assert r.status_code == 200
    html = r.content.decode("utf-8")
    assert "Hand Replay" in html
    assert f">{hid}<" in html or hid in html  # hand id chip present
    assert 'id="action-log"' in html
    assert "card" in html  # board/cards present
