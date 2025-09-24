import json

import pytest
from django.test import Client


def _post(c: Client, url: str, payload: dict):
    return c.post(url, data=json.dumps(payload), content_type="application/json")


def _extract_opp_hole(html: str) -> str:
    """Return a small slice of HTML around the opponent hole-cards container."""
    key = 'id="opp-hole"'
    i = html.find(key)
    if i == -1:
        return ""
    return html[max(0, i - 80) : i + 400]


@pytest.mark.django_db
def test_reveal_rules_teach_off_fold_hides_opp():
    c = Client()
    # Create session and hand
    sid = _post(c, "/api/v1/session/start", {}).json()["session_id"]
    hid = _post(c, "/api/v1/hand/start", {"session_id": sid, "seed": 101}).json()["hand_id"]

    # Force teach OFF via session
    s = c.session
    s["teach"] = False
    s.save()

    # Drive to fold end quickly using REST API (act as current player)
    for _ in range(20):
        body = c.get(f"/api/v1/hand/state/{hid}").json()
        if body.get("state", {}).get("street") == "complete":
            break
        legal = set(body.get("legal_actions") or [])
        if "fold" in legal:
            _post(c, f"/api/v1/hand/act/{hid}", {"action": "fold"})
            break
        elif "check" in legal:
            _post(c, f"/api/v1/hand/act/{hid}", {"action": "check"})
        elif "call" in legal:
            _post(c, f"/api/v1/hand/act/{hid}", {"action": "call"})
        else:
            _post(c, f"/api/v1/hand/act/{hid}", {"action": list(legal)[0]})

    # SSR page should hide opponent cards (cid="?") in opp-hole region
    page = c.get(f"/api/v1/ui/game/{sid}/{hid}").content.decode("utf-8")
    frag = _extract_opp_hole(page)
    assert frag, "opp-hole container not found"
    assert frag.count('cid="?"') >= 2, "Teach OFF + fold end should keep opponent cards facedown"


@pytest.mark.django_db
def test_reveal_rules_teach_off_showdown_reveals_opp():
    c = Client()
    sid = _post(c, "/api/v1/session/start", {}).json()["session_id"]
    hid = _post(c, "/api/v1/hand/start", {"session_id": sid, "seed": 202}).json()["hand_id"]

    # Teach OFF
    s = c.session
    s["teach"] = False
    s.save()

    # Try to check/call down to showdown
    for _ in range(120):
        body = c.get(f"/api/v1/hand/state/{hid}").json()
        if body.get("state", {}).get("street") == "complete":
            break
        legal = set(body.get("legal_actions") or [])
        if "check" in legal:
            _post(c, f"/api/v1/hand/act/{hid}", {"action": "check"})
        elif "call" in legal:
            _post(c, f"/api/v1/hand/act/{hid}", {"action": "call"})
        elif "fold" in legal:
            # Avoid ending by fold; choose the next safest action if possible
            others = [a for a in legal if a not in {"fold"}]
            if others:
                a = others[0]
                payload = {"action": a}
                if a in {"bet", "raise"}:
                    payload["amount"] = 1
                _post(c, f"/api/v1/hand/act/{hid}", payload)
            else:
                _post(c, f"/api/v1/hand/act/{hid}", {"action": "fold"})
        else:
            a = list(legal)[0]
            payload = {"action": a}
            if a in {"bet", "raise"}:
                payload["amount"] = 1
            _post(c, f"/api/v1/hand/act/{hid}", payload)

    page = c.get(f"/api/v1/ui/game/{sid}/{hid}").content.decode("utf-8")
    frag = _extract_opp_hole(page)
    assert frag, "opp-hole container not found"
    assert 'cid="?"' not in frag, "Teach OFF + showdown end should reveal opponent cards"


@pytest.mark.django_db
def test_reveal_rules_teach_on_always_reveals_opp():
    c = Client()
    sid = _post(c, "/api/v1/session/start", {}).json()["session_id"]
    hid = _post(c, "/api/v1/hand/start", {"session_id": sid, "seed": 303}).json()["hand_id"]

    # Teach ON (default True); end by fold quickly
    for _ in range(20):
        body = c.get(f"/api/v1/hand/state/{hid}").json()
        if body.get("state", {}).get("street") == "complete":
            break
        legal = set(body.get("legal_actions") or [])
        if "fold" in legal:
            _post(c, f"/api/v1/hand/act/{hid}", {"action": "fold"})
            break
        elif "check" in legal:
            _post(c, f"/api/v1/hand/act/{hid}", {"action": "check"})
        elif "call" in legal:
            _post(c, f"/api/v1/hand/act/{hid}", {"action": "call"})
        else:
            _post(c, f"/api/v1/hand/act/{hid}", {"action": list(legal)[0]})

    page = c.get(f"/api/v1/ui/game/{sid}/{hid}").content.decode("utf-8")
    frag = _extract_opp_hole(page)
    assert frag, "opp-hole container not found"
    assert 'cid="?"' not in frag, "Teach ON should always reveal opponent cards"
