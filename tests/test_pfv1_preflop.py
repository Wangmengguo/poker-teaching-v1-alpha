import os

from poker_core.domain.actions import LegalAction
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


def test_sb_rfi_hit(monkeypatch):
    _set_env(monkeypatch, debug=1)
    bb = 50
    # SB(button=0) acts first
    p0 = _P(invested=bb // 2, hole=["Ah", "Qd"])  # AQo
    p1 = _P(invested=bb, hole=["7c", "7d"])  # irrelevant
    gs = _GS(button=0, to_act=0, bb=bb, p0=p0, p1=p1)
    acts = [
        LegalAction(action="check"),
        LegalAction(action="bet", min=bb, max=100 * bb),
    ]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 0)
    assert r["suggested"]["action"] in {"bet", "raise"}
    assert r["suggested"]["amount"] == int(round(2.5 * bb))
    assert r.get("meta", {}).get("open_bb") == 2.5
    assert any(x.get("code") == "PF_OPEN_RANGE_HIT" for x in r["rationale"])
    assert r["confidence"] >= 0.75
    # bucket should not appear on RFI
    assert "bucket" not in (r.get("meta", {}) or {})


def test_sb_rfi_hit_with_call_option(monkeypatch):
    _set_env(monkeypatch, debug=1)
    bb = 50
    p0 = _P(invested=bb // 2, hole=["Ah", "Qd"])  # AQo
    p1 = _P(invested=bb, hole=["7c", "7d"])  # irrelevant
    gs = _GS(button=0, to_act=0, bb=bb, p0=p0, p1=p1)
    to_call = bb // 2
    acts = [
        LegalAction(action="fold"),
        LegalAction(action="call", to_call=to_call),
        LegalAction(action="raise", min=bb, max=100 * bb),
    ]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 0)
    assert r["suggested"]["action"] == "raise"
    assert r["suggested"]["amount"] == int(round(2.5 * bb))
    assert r.get("meta", {}).get("open_bb") == 2.5
    assert any(x.get("code") == "PF_OPEN_RANGE_HIT" for x in r["rationale"])


def test_sb_rfi_miss(monkeypatch):
    _set_env(monkeypatch)
    bb = 50
    p0 = _P(invested=bb // 2, hole=["Td", "6c"])  # T6o not in RFI
    p1 = _P(invested=bb)
    gs = _GS(button=0, to_act=0, bb=bb, p0=p0, p1=p1)
    acts = [LegalAction(action="check")]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 0)
    assert r["suggested"]["action"] == "check"
    assert 0.5 <= r["confidence"] <= 0.7


def test_bb_small_call_defend(monkeypatch):
    _set_env(monkeypatch)
    bb = 50
    # SB opened to 2.5x → SB invested 2.5bb, BB invested 1bb
    p0 = _P(invested=int(2.5 * bb), hole=["Ah", "Qd"])  # opener irrelevant
    p1 = _P(invested=bb, hole=["9h", "8h"])  # 98s
    gs = _GS(button=0, to_act=1, bb=bb, p0=p0, p1=p1)
    to_call = int(1.5 * bb)
    acts = [LegalAction(action="fold"), LegalAction(action="call", to_call=to_call)]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 1)
    assert r["suggested"]["action"] == "call"
    assert r.get("meta", {}).get("bucket") == "small"
    assert any(x.get("code") == "PF_DEFEND_PRICE_OK" for x in r["rationale"])


def test_bb_small_reraise(monkeypatch):
    _set_env(monkeypatch)
    bb = 50
    p0 = _P(invested=int(2.5 * bb))
    p1 = _P(invested=bb, hole=["As", "Qs"])  # AQs
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
    # target ~ 8bb
    assert abs(r.get("meta", {}).get("reraise_to_bb", 0) - 8) <= 1
    assert r.get("meta", {}).get("bucket") == "small"


def test_bb_mid_call(monkeypatch):
    _set_env(monkeypatch)
    bb = 50
    p0 = _P(invested=int(3.5 * bb))
    p1 = _P(invested=bb, hole=["Qh", "9c"])  # Q9o
    gs = _GS(button=0, to_act=1, bb=bb, p0=p0, p1=p1)
    to_call = int(2.5 * bb)
    acts = [
        LegalAction(action="fold"),
        LegalAction(action="call", to_call=to_call),
        LegalAction(action="raise", min=int(6 * bb), max=int(60 * bb)),
    ]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 1)
    assert r["suggested"]["action"] == "call"
    assert any(x.get("code") == "PF_DEFEND_PRICE_OK" for x in r["rationale"])


def test_3bet_short_cap_clamped(monkeypatch):
    _set_env(monkeypatch)
    bb = 50
    p0 = _P(invested=int(2.5 * bb))
    p1 = _P(invested=bb, hole=["As", "Ks"])  # AKs in 3bet range
    gs = _GS(button=0, to_act=1, bb=bb, p0=p0, p1=p1)
    to_call = int(1.5 * bb)
    # cap via max smaller than target
    acts = [
        LegalAction(action="fold"),
        LegalAction(action="call", to_call=to_call),
        LegalAction(action="raise", min=int(6 * bb), max=int(7 * bb)),
    ]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 1)
    assert r["suggested"]["action"] == "raise"
    assert any(x.get("code") == "W_CLAMPED" for x in r["rationale"])


def test_illegal_combo_fallback(monkeypatch):
    _set_env(monkeypatch, debug=1)
    bb = 50
    p0 = _P(invested=bb // 2, hole=["Xq", "Yc"])  # invalid
    p1 = _P(invested=bb)
    gs = _GS(button=0, to_act=0, bb=bb, p0=p0, p1=p1)
    acts = [LegalAction(action="check")]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 0)
    assert r["suggested"]["action"] == "check"
    assert any(x.get("code") == "CFG_FALLBACK_USED" for x in r["rationale"])
    if "debug" in r:
        cfgv = r["debug"]["meta"]["config_versions"]
        assert {"open", "vs", "modes"}.issubset(cfgv.keys())


def test_rfi_no_raise_fallback(monkeypatch):
    _set_env(monkeypatch)
    bb = 50
    p0 = _P(invested=bb // 2, hole=["Ah", "Qd"])  # AQo in RFI
    p1 = _P(invested=bb)
    gs = _GS(button=0, to_act=0, bb=bb, p0=p0, p1=p1)
    acts = [LegalAction(action="check")]  # no bet/raise
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 0)
    assert r["suggested"]["action"] == "check"
    # Either fallback or no-legal-raise hint present
    assert (
        any(x.get("code") in {"PF_NO_LEGAL_RAISE"} for x in r["rationale"])
        or r["confidence"] <= 0.6
    )


def test_big_open_mid_3bet_grows(monkeypatch):
    _set_env(monkeypatch)
    bb = 50
    # SB open 3x → invested 3bb
    p0 = _P(invested=int(3.0 * bb))
    p1 = _P(invested=bb, hole=["As", "Qs"])  # AQs in reraise.mid according to config
    gs = _GS(button=0, to_act=1, bb=bb, p0=p0, p1=p1)
    to_call = int(2.0 * bb)
    acts = [
        LegalAction(action="fold"),
        LegalAction(action="call", to_call=to_call),
        LegalAction(action="raise", min=int(6 * bb), max=int(60 * bb)),
    ]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 1)
    # around 9bb when IP vs 3x
    assert r["suggested"]["action"] == "raise"
    assert r.get("meta", {}).get("reraise_to_bb") in {8, 9, 10}


def test_pot_odds_equal_threshold_is_ok(monkeypatch):
    # Override thresholds to match exact pot_odds
    import poker_core.suggest.preflop_tables as t

    def _fake_modes(_rel):
        return (
            {
                "HU": {
                    "open_bb": 2.5,
                    "defend_threshold_ip": 0.25,
                    "defend_threshold_oop": 0.25,
                }
            },
            1,
        )

    t._load_modes.cache_clear()
    monkeypatch.setattr(t, "_load_modes", _fake_modes)
    _set_env(monkeypatch)
    bb = 50
    # pot_now = 4*bb, to_call= (4/3)*bb → pot_odds=0.25
    p0 = _P(invested=int(3 * bb))
    p1 = _P(invested=int(1 * bb), hole=["9h", "8h"])  # in call.small
    gs = _GS(button=0, to_act=1, bb=bb, p0=p0, p1=p1)
    to_call = int((4 / 3) * bb)
    acts = [LegalAction(action="fold"), LegalAction(action="call", to_call=to_call)]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 1)
    assert r["suggested"]["action"] == "call"


def test_rfi_amount_clamped(monkeypatch):
    _set_env(monkeypatch)
    bb = 50
    p0 = _P(invested=bb // 2, hole=["Ah", "Qd"])  # AQo
    p1 = _P(invested=bb)
    gs = _GS(button=0, to_act=0, bb=bb, p0=p0, p1=p1)
    # bet min above open amount (force clamp)
    acts = [LegalAction(action="check"), LegalAction(action="bet", min=200, max=500)]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 0)
    assert (
        any(x.get("code") == "W_CLAMPED" for x in r["rationale"]) or r["suggested"]["amount"] >= 200
    )


def test_min_reopen_adjusted(monkeypatch):
    _set_env(monkeypatch)
    bb = 50
    p0 = _P(invested=int(2.5 * bb))
    p1 = _P(invested=bb, hole=["As", "Qs"])  # AQs
    gs = _GS(button=0, to_act=1, bb=bb, p0=p0, p1=p1)
    to_call = int(1.5 * bb)
    # set raise.min above computed target to trigger adjustment
    acts = [
        LegalAction(action="fold"),
        LegalAction(action="call", to_call=to_call),
        LegalAction(action="raise", min=int(10 * bb), max=int(60 * bb)),
    ]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 1)
    assert r["suggested"]["action"] == "raise"
    # to-amount semantics: lifted to raise.min
    assert r["suggested"]["amount"] == int(10 * bb)
    assert any(x.get("code") == "PF_DEFEND_3BET_MIN_RAISE_ADJUSTED" for x in r["rationale"])


def test_3bet_overlap_prefers_reraise(monkeypatch):
    # When a combo appears in both call and reraise sets, prefer reraise
    import poker_core.suggest.preflop_tables as t

    t._load_modes.cache_clear()
    t._load_open.cache_clear()
    t._load_vs.cache_clear()

    def _fake_vs(_rel):
        return ({"BB_vs_SB": {"small": {"call": {"AQs"}, "reraise": {"AQs"}}}}, 1)

    monkeypatch.setattr(t, "_load_vs", _fake_vs)
    _set_env(monkeypatch)
    bb = 50
    p0 = _P(invested=int(2.5 * bb))
    p1 = _P(invested=bb, hole=["As", "Qs"])  # AQs in both sets
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


def test_3bet_shortstack_about_5bb(monkeypatch):
    # Effective stack ~5bb caps reraise_to_bb
    _set_env(monkeypatch)
    bb = 50
    p0 = _P(invested=int(2.5 * bb))
    # BB stack 5bb
    p1 = _P(stack=int(5 * bb), invested=bb, hole=["As", "Qs"])  # AQs in reraise.small
    gs = _GS(button=0, to_act=1, bb=bb, p0=p0, p1=p1)
    to_call = int(1.5 * bb)
    acts = [
        LegalAction(action="fold"),
        LegalAction(action="call", to_call=to_call),
        # Tight raise window to force clamp if overshoot
        LegalAction(action="raise", min=int(3 * bb), max=int(6 * bb)),
    ]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 1)
    assert r["suggested"]["action"] == "raise"
    # Either computed cap or service clamp ensures within max
    assert r["suggested"]["amount"] <= int(6 * bb)


def test_3bet_min_equals_cap_boundary(monkeypatch):
    # Set cap to equal the legal raise.max, ensure no overshoot
    import poker_core.suggest.preflop_tables as t

    def _fake_modes(_rel):
        return (
            {
                "HU": {
                    "open_bb": 2.5,
                    "defend_threshold_ip": 0.42,
                    "defend_threshold_oop": 0.38,
                    "reraise_ip_mult": 4.0,
                    "cap_ratio": 0.9,
                }
            },
            1,
        )

    t._load_modes.cache_clear()
    monkeypatch.setattr(t, "_load_modes", _fake_modes)

    _set_env(monkeypatch)
    bb = 50
    # Effective 10bb → cap=9bb; set raise.max=9bb
    p0 = _P(invested=int(2.5 * bb))
    p1 = _P(stack=int(10 * bb), invested=bb, hole=["As", "Qs"])  # AQs
    gs = _GS(button=0, to_act=1, bb=bb, p0=p0, p1=p1)
    to_call = int(1.5 * bb)
    acts = [
        LegalAction(action="fold"),
        LegalAction(action="call", to_call=to_call),
        LegalAction(action="raise", min=int(4 * bb), max=int(9 * bb)),
    ]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 1)
    assert r["suggested"]["amount"] == int(9 * bb)


def test_3bet_no_fold_legal_fallback(monkeypatch):
    # No 'fold' in legal actions → fallback must not return fold
    _set_env(monkeypatch)
    bb = 50
    p0 = _P(invested=int(3.5 * bb))
    p1 = _P(invested=bb, hole=["Qh", "9c"])  # out of range
    gs = _GS(button=0, to_act=1, bb=bb, p0=p0, p1=p1)
    to_call = int(2.5 * bb)
    acts = [LegalAction(action="check"), LegalAction(action="call", to_call=to_call)]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 1)
    assert r["suggested"]["action"] in {"check", "call"}


def test_4bet_value_small_bucket(monkeypatch):
    # Enable 4bet; AA in small bucket fourbet set
    _set_env(monkeypatch, debug=1)
    os.environ["SUGGEST_PREFLOP_ENABLE_4BET"] = "1"
    bb = 50
    # SB actor facing 3bet to 9bb: i_me=2.5bb, i_opp=9bb → to_call=6.5bb
    p0 = _P(invested=int(2.5 * bb), hole=["Ad", "Ac"])  # AA
    p1 = _P(invested=int(9 * bb))
    gs = _GS(button=0, to_act=0, bb=bb, p0=p0, p1=p1)
    to_call = int(6.5 * bb)
    acts = [
        LegalAction(action="call", to_call=to_call),
        LegalAction(action="raise", min=int(12 * bb), max=int(100 * bb)),
    ]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 0)
    assert r["suggested"]["action"] == "raise"
    assert r.get("meta", {}).get("fourbet_to_bb") is not None
    assert any(x.get("code") == "PF_ATTACK_4BET" for x in r["rationale"])
    # preflop should not return size_tag
    assert "size_tag" not in (r.get("meta") or {})


def test_4bet_bluff_small_bucket(monkeypatch):
    _set_env(monkeypatch)
    os.environ["SUGGEST_PREFLOP_ENABLE_4BET"] = "1"
    bb = 50
    p0 = _P(invested=int(2.5 * bb), hole=["As", "5s"])  # A5s in small.fourbet
    p1 = _P(invested=int(9 * bb))
    gs = _GS(button=0, to_act=0, bb=bb, p0=p0, p1=p1)
    to_call = int(6.5 * bb)
    acts = [
        LegalAction(action="call", to_call=to_call),
        LegalAction(action="raise", min=int(12 * bb), max=int(100 * bb)),
    ]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 0)
    assert r["suggested"]["action"] == "raise"


def test_4bet_min_reopen_adjusted(monkeypatch):
    _set_env(monkeypatch)
    os.environ["SUGGEST_PREFLOP_ENABLE_4BET"] = "1"
    bb = 50
    p0 = _P(invested=int(2.5 * bb), hole=["As", "Ks"])  # AKs in fourbet.small
    p1 = _P(invested=int(9 * bb))
    gs = _GS(button=0, to_act=0, bb=bb, p0=p0, p1=p1)
    to_call = int(6.5 * bb)
    # Raise.min above computed to trigger min-adjust
    acts = [
        LegalAction(action="call", to_call=to_call),
        LegalAction(action="raise", min=int(24 * bb), max=int(100 * bb)),
    ]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 0)
    assert any(x.get("code") == "PF_ATTACK_4BET_MIN_RAISE_ADJUSTED" for x in r["rationale"])


def test_4bet_min_adjust_and_clamped_both(monkeypatch):
    # Force both min-reopen adjustment and service clamp to occur
    _set_env(monkeypatch)
    os.environ["SUGGEST_PREFLOP_ENABLE_4BET"] = "1"
    bb = 50
    p0 = _P(invested=int(2.5 * bb), hole=["As", "Ks"])  # AKs
    p1 = _P(invested=int(9 * bb))
    gs = _GS(button=0, to_act=0, bb=bb, p0=p0, p1=p1)
    to_call = int(6.5 * bb)
    # Intentionally set inconsistent raise bounds to trigger both signals
    acts = [
        LegalAction(action="call", to_call=to_call),
        LegalAction(action="raise", min=int(24 * bb), max=int(20 * bb)),
    ]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 0)
    codes = {x.get("code") for x in r["rationale"]}
    assert "PF_ATTACK_4BET_MIN_RAISE_ADJUSTED" in codes
    assert "W_CLAMPED" in codes


def test_4bet_short_cap(monkeypatch):
    _set_env(monkeypatch)
    os.environ["SUGGEST_PREFLOP_ENABLE_4BET"] = "1"
    bb = 50
    # Hero stack ~5bb, cap will be small; ensure legal clamp works
    p0 = _P(stack=int(5 * bb), invested=int(2.5 * bb), hole=["As", "Ks"])  # AKs
    p1 = _P(invested=int(9 * bb))
    gs = _GS(button=0, to_act=0, bb=bb, p0=p0, p1=p1)
    to_call = int(6.5 * bb)
    acts = [
        LegalAction(action="call", to_call=to_call),
        LegalAction(action="raise", min=int(4 * bb), max=int(6 * bb)),
    ]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 0)
    assert r["suggested"]["action"] == "raise"
    assert r["suggested"]["amount"] <= int(6 * bb)


def test_4bet_missing_keys_fallback(monkeypatch):
    # Patch vs table to drop fourbet keys → fallback
    import poker_core.suggest.preflop_tables as t

    t._load_vs.cache_clear()

    def _fake_vs(_rel):
        return ({"SB_vs_BB_3bet": {}}, 1)

    monkeypatch.setattr(t, "_load_vs", _fake_vs)

    _set_env(monkeypatch)
    os.environ["SUGGEST_PREFLOP_ENABLE_4BET"] = "1"
    bb = 50
    p0 = _P(invested=int(2.5 * bb), hole=["Ad", "Ac"])  # AA but no config keys
    p1 = _P(invested=int(9 * bb))
    gs = _GS(button=0, to_act=0, bb=bb, p0=p0, p1=p1)
    to_call = int(6.5 * bb)
    acts = [
        LegalAction(action="call", to_call=to_call),
        LegalAction(action="raise", min=int(12 * bb), max=int(100 * bb)),
    ]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 0)
    # Should not crash; conservative action chosen (call or fold/check)
    assert r["suggested"]["action"] in {"call", "fold", "check"}


def test_4bet_no_legal_reraise(monkeypatch):
    _set_env(monkeypatch)
    os.environ["SUGGEST_PREFLOP_ENABLE_4BET"] = "1"
    bb = 50
    p0 = _P(invested=int(2.5 * bb), hole=["Ad", "Ac"])  # AA
    p1 = _P(invested=int(9 * bb))
    gs = _GS(button=0, to_act=0, bb=bb, p0=p0, p1=p1)
    to_call = int(6.5 * bb)
    # No raise action available
    acts = [LegalAction(action="call", to_call=to_call)]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 0)
    assert r["suggested"]["action"] == "call"


def test_rounding_stability(monkeypatch):
    _set_env(monkeypatch)
    bb = 50
    p0 = _P(invested=bb // 2, hole=["Ah", "Qd"])  # AQo
    p1 = _P(invested=bb)
    gs = _GS(button=0, to_act=0, bb=bb, p0=p0, p1=p1)
    acts = [LegalAction(action="check"), LegalAction(action="bet", min=1, max=1000)]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 0)
    assert r["suggested"]["amount"] == 125


def test_bb_limped_check(monkeypatch):
    _set_env(monkeypatch)
    bb = 50
    # Limped pot: SB has limped; BB to act with to_call==0
    p0 = _P(
        invested=int(1 * bb)
    )  # SB 2bb? For simplicity, set invested to 1bb to simulate partial; to_call=0 via acts
    p1 = _P(invested=int(1 * bb), hole=["7h", "5c"])  # BB
    gs = _GS(button=0, to_act=1, bb=bb, p0=p0, p1=p1)
    acts = [LegalAction(action="check")]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 1)
    assert r["suggested"]["action"] == "check"
    # No meta for vs-raise here
    assert not r.get("meta")


def test_vs_table_missing_buckets_fallback(monkeypatch):
    _set_env(monkeypatch, debug=1)
    import poker_core.suggest.preflop_tables as t

    def _fake_load_vs(_):
        return ({}, 0)

    t._load_vs.cache_clear()
    monkeypatch.setattr(t, "_load_vs", _fake_load_vs)
    bb = 50
    p0 = _P(invested=int(2.5 * bb))
    p1 = _P(invested=bb, hole=["7h", "5c"])  # any hand
    gs = _GS(button=0, to_act=1, bb=bb, p0=p0, p1=p1)
    to_call = int(1.5 * bb)
    acts = [LegalAction(action="fold"), LegalAction(action="call", to_call=to_call)]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 1)
    assert r["suggested"]["action"] in {"fold", "check"}
    assert any(x.get("code") == "CFG_FALLBACK_USED" for x in r["rationale"])
    assert r.get("debug", {}).get("meta", {}).get("config_versions", {}).get("vs") == 0


def test_config_versions_debug_and_profile(monkeypatch):
    _set_env(monkeypatch, debug=1)
    # Use external profile name
    monkeypatch.setenv("SUGGEST_CONFIG_DIR", "/tmp/loose")
    bb = 50
    p0 = _P(invested=bb // 2, hole=["Td", "6c"])  # miss RFI
    p1 = _P(invested=bb)
    gs = _GS(button=0, to_act=0, bb=bb, p0=p0, p1=p1)
    acts = [LegalAction(action="check")]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 0)
    assert r.get("debug", {}).get("meta", {}).get("config_profile") == "loose"
    cfgv = r["debug"]["meta"]["config_versions"]
    assert {"open", "vs", "modes"}.issubset(cfgv.keys())


def test_sb_limp_complete_has_rationale(monkeypatch):
    # Ensure SB limp-complete always carries PF_LIMP_COMPLETE_BLIND rationale
    _set_env(monkeypatch, debug=1)
    bb = 50
    p0 = _P(invested=bb // 2, hole=["7h", "2d"])  # weak, not in RFI
    p1 = _P(invested=bb)
    gs = _GS(button=0, to_act=0, bb=bb, p0=p0, p1=p1)
    # Only call is available; to_call=0.5bb
    acts = [LegalAction(action="check"), LegalAction(action="call", to_call=bb // 2)]
    _patch_acts(monkeypatch, acts)
    r = build_suggestion(gs, 0)
    assert r["suggested"]["action"] == "call"
    codes = {x.get("code") for x in (r.get("rationale") or [])}
    assert "PF_LIMP_COMPLETE_BLIND" in codes
