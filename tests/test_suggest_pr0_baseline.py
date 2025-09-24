import json

import pytest
from poker_core.domain.actions import LegalAction
from poker_core.suggest.config_loader import load_json_cached
from poker_core.suggest.service import _build_observation, build_suggestion
from poker_core.suggest.utils import active_player_count, stable_roll


def test_utils_stable_roll_is_stable():
    hid = "h_123456"
    got = [stable_roll(hid, 37) for _ in range(100)]
    assert len(set(got)) == 1  # stable per id

    # crude distribution check over many ids
    ids = [f"h_{i}" for i in range(2000)]
    hits = sum(1 for x in ids if stable_roll(x, 37))
    ratio = hits / len(ids)
    assert 0.28 <= ratio <= 0.46  # loose bounds to avoid flakiness


def test_config_loader_ttl_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("SUGGEST_CONFIG_DIR", str(tmp_path))
    fp = tmp_path / "foo.json"
    fp.write_text(json.dumps({"hello": "world"}), encoding="utf-8")

    data, ver1 = load_json_cached("foo.json", ttl_seconds=60)
    assert data.get("hello") == "world"
    assert isinstance(ver1, int) and ver1 >= 0

    # corrupt file, but within TTL it should still return cached value
    fp.write_text("{not-json}", encoding="utf-8")
    data2, ver2 = load_json_cached("foo.json", ttl_seconds=60)
    assert data2.get("hello") == "world"
    assert ver2 == ver1

    # missing file returns empty + version 0
    empty, ver0 = load_json_cached("missing.json", ttl_seconds=60)
    assert empty == {}
    assert ver0 == 0


class _P:
    def __init__(self, stack=0, invested=0, hole=None):
        self.stack = stack
        self.invested_street = invested
        self.hole = hole or []


class _GS:
    def __init__(self):
        self.hand_id = "h_x"
        self.street = "preflop"
        self.bb = 50
        self.pot = 0
        self.board = []
        self.button = 0
        self.players = (_P(), _P())
        self.to_act = 0


def test_build_observation_defaults():
    gs = _GS()
    acts = [LegalAction(action="check")]
    obs, pre = _build_observation(gs, 0, acts)
    assert obs.board_texture == "na"
    # pot_now = 0 → spr = inf → bucket 'na'
    assert obs.spr_bucket == "na"
    # HU preflop: button actor (0) is OOP
    assert obs.ip is False


def test_service_response_compat(monkeypatch):
    # Monkeypatch legal_actions_struct to avoid requiring a full engine state
    import poker_core.suggest.service as svc

    gs = _GS()

    def _fake_legal_actions_struct(_):
        return [LegalAction(action="check")]

    monkeypatch.setattr(svc, "legal_actions_struct", _fake_legal_actions_struct)
    # Ensure version selection does not change behavior in PR-0
    monkeypatch.setenv("SUGGEST_POLICY_VERSION", "v0")

    resp = build_suggestion(gs, 0)
    # Backward-compatible keys
    assert resp["hand_id"] == gs.hand_id
    assert resp["actor"] == 0
    assert resp["policy"]
    assert isinstance(resp.get("rationale"), list)
    assert isinstance(resp.get("suggested"), dict)
    assert resp.get("confidence") is not None
    # Preflop should not include size_tag
    assert "size_tag" not in resp["suggested"]


def test_active_player_count_guard():
    class _G2:
        def __init__(self, n):
            self.players = [None] * n

    assert active_player_count(_G2(2)) == 2
    with pytest.raises(AssertionError):
        active_player_count(_G2(3))
