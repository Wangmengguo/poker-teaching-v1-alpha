import json
import re

import pytest
from django.test import Client


@pytest.mark.django_db
def test_deal_then_replay_basic():
    c = Client()
    r = c.post(
        "/api/v1/table/deal",
        data=json.dumps({"seed": 42, "num_players": 2}),
        content_type="application/json",
    )
    assert r.status_code == 200
    body = r.json()
    for key in [
        "hand_id",
        "seed",
        "engine_commit",
        "schema_version",
        "players",
        "annotations",
    ]:
        assert key in body and body[key] is not None
    assert re.match(r"^h_[0-9a-f]{8}$", body["hand_id"])
    assert isinstance(body["players"], list)
    assert isinstance(body["annotations"], list)
    assert len(body["players"]) == len(body["annotations"])

    hand_id = body["hand_id"]
    rep = c.get(f"/api/v1/replay/{hand_id}")
    assert rep.status_code == 200
    rep_body = rep.json()
    for key in [
        "hand_id",
        "seed",
        "engine_commit",
        "schema_version",
        "steps",
        "players",
        "annotations",
    ]:
        assert key in rep_body
