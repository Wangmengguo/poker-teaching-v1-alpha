import json

import pytest
from api.models import Replay
from django.test import Client


@pytest.mark.django_db
def test_metrics_increment_and_persistence():
    c = Client()
    m0 = c.get("/api/v1/metrics").json().get("deals_total", 0)
    resp = c.post(
        "/api/v1/table/deal",
        data=json.dumps({"seed": 7, "num_players": 2}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    hand_id = resp.json()["hand_id"]
    m1 = c.get("/api/v1/metrics").json()["deals_total"]
    assert m1 == m0 + 1
    assert Replay.objects.filter(hand_id=hand_id).exists()
