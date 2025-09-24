from __future__ import annotations

import os

import pytest
from poker_core.domain.actions import LegalAction
from poker_core.suggest.context import SuggestContext, SuggestFlags, SuggestProfile
from poker_core.suggest.service import build_suggestion


class _P:
    def __init__(self, stack=10000, invested=0, hole=None):
        self.stack = stack
        self.invested_street = invested
        self.hole = hole or []


class _GS:
    def __init__(self, *, hand_id="h_x", button=0, to_act=0, bb=50, pot=0, p0=None, p1=None):
        self.hand_id = hand_id
        self.session_id = "s_x"
        self.street = "preflop"
        self.bb = bb
        self.pot = pot
        self.button = button
        self.players = (p0 or _P(), p1 or _P())
        self.to_act = to_act


def _set_env(monkeypatch, policy="v1_preflop", debug=0):
    monkeypatch.setenv("SUGGEST_POLICY_VERSION", policy)
    monkeypatch.setenv("SUGGEST_V1_ROLLOUT_PCT", "0")
    monkeypatch.setenv("SUGGEST_DEBUG", "1" if debug else "0")
    monkeypatch.delenv("SUGGEST_CONFIG_DIR", raising=False)


def _patch_acts(monkeypatch, acts):
    import poker_core.suggest.service as svc

    def _fake(_):
        return acts

    monkeypatch.setattr(svc, "legal_actions_struct", _fake)


def _ctx_for_plan() -> SuggestContext:
    modes = {
        "HU": {
            "open_bb": 2.5,
            "defend_threshold_ip": 0.42,
            "defend_threshold_oop": 0.38,
            "reraise_ip_mult": 3.0,
            "reraise_oop_mult": 3.5,
            "reraise_oop_offset": 0.5,
            "cap_ratio": 0.9,
            "fourbet_ip_mult": 2.2,
            "cap_ratio_4b": 0.85,
            "threebet_bucket_small_le": 9,
            "threebet_bucket_mid_le": 11,
        }
    }
    open_tab = {"SB": {"AKs"}, "BB": set()}
    vs_tab = {
        "BB_vs_SB": {"small": {"reraise": {"AKs"}, "call": set()}},
        "SB_vs_BB_3bet": {
            "small": {"fourbet": {"AKs"}, "call": {"A5s"}},
            "mid": {"call": {"A5s"}},
        },
    }
    return SuggestContext(
        modes=modes,
        open_table=open_tab,
        vs_table=vs_tab,
        versions={"open": 1, "vs": 1, "modes": 1},
        flags=SuggestFlags(enable_flop_value_raise=True),
        profile=SuggestProfile(strategy_name="medium", config_profile="builtin"),
    )


@pytest.fixture
def patch_ctx(monkeypatch):
    import poker_core.suggest.service as svc

    monkeypatch.setattr(svc.SuggestContext, "build", staticmethod(_ctx_for_plan))


def test_sb_rfi_plan_contains_thresholds(monkeypatch, patch_ctx):
    _set_env(monkeypatch)
    bb = 50
    # SB first to act, hole AKs (in SB open range)
    p0 = _P(invested=bb // 2, hole=["As", "Ks"])  # AKs
    p1 = _P(invested=bb)
    gs = _GS(button=0, to_act=0, bb=bb, p0=p0, p1=p1)
    acts = [LegalAction(action="check"), LegalAction(action="bet", min=bb, max=100 * bb)]
    _patch_acts(monkeypatch, acts)

    r = build_suggestion(gs, 0)
    plan = (r.get("meta") or {}).get("plan", "")
    assert "≤9bb" in plan and "≤11bb" in plan


def test_bb_defend_plan_for_3bet(monkeypatch, patch_ctx):
    _set_env(monkeypatch)
    bb = 50
    # Facing SB open (2.5x), BB last to act; combo in reraise set
    p0 = _P(invested=int(2.5 * bb))
    p1 = _P(invested=bb, hole=["As", "Ks"])  # AKs
    gs = _GS(button=0, to_act=1, bb=bb, p0=p0, p1=p1)
    to_call = int(1.5 * bb)
    acts = [
        LegalAction(action="fold"),
        LegalAction(action="call", to_call=to_call),
        LegalAction(action="raise", min=int(4 * bb), max=int(40 * bb)),
    ]
    _patch_acts(monkeypatch, acts)

    r = build_suggestion(gs, 1)
    assert r["suggested"]["action"] == "raise"
    plan = (r.get("meta") or {}).get("plan", "")
    assert "四bet" in plan  # "若遭四bet 默认弃牌；仅 QQ+/AK 继续。"


def test_sb_vs_threebet_call_plan_contains_thresholds(monkeypatch, patch_ctx):
    _set_env(monkeypatch)
    os.environ["SUGGEST_PREFLOP_ENABLE_4BET"] = "1"
    bb = 50
    # SB opened 2.5x; BB 3bet to 9x → SB facing 6.5bb
    p0 = _P(invested=int(2.5 * bb), hole=["As", "5s"])  # A5s in call set
    p1 = _P(invested=int(9 * bb))
    gs = _GS(button=0, to_act=0, bb=bb, p0=p0, p1=p1)
    to_call = int(6.5 * bb)
    acts = [
        LegalAction(action="call", to_call=to_call),
        LegalAction(action="raise", min=int(12 * bb), max=int(100 * bb)),
    ]
    _patch_acts(monkeypatch, acts)

    r = build_suggestion(gs, 0)
    assert r["suggested"]["action"] == "call"
    plan = (r.get("meta") or {}).get("plan", "")
    assert "≤9bb" in plan and "≤11bb" in plan
