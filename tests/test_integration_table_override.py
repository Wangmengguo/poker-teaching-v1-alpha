from poker_core.state_hu import apply_action
from poker_core.state_hu import legal_actions as engine_legal_actions
from poker_core.state_hu import start_hand
from poker_core.state_hu import start_session
from poker_core.suggest.service import build_suggestion


def _act(gs, name, amt=None):
    if amt is None:
        return apply_action(gs, name)
    return apply_action(gs, name, amt)


def test_flop_limped_ip_uses_table(monkeypatch):
    monkeypatch.setenv("SUGGEST_POLICY_DIR", "artifacts/policies")
    cfg = start_session(init_stack=200, sb=1, bb=2)
    gs = start_hand(cfg, session_id="sA", hand_id="hA1", button=0, seed=42)
    # Preflop limp/check to flop (limped pot).
    # Engine requires SB to complete blind (call); then BB may check.
    la = set(engine_legal_actions(gs))
    assert ("call" in la) or ("check" in la)
    if "call" in la:
        gs = _act(gs, "call")  # SB limp complete
    else:
        gs = _act(gs, "check")
    la = set(engine_legal_actions(gs))
    assert "check" in la
    gs = _act(gs, "check")  # BB → flop
    # Now it's limped flop; actor is BB (non-button) first to act. Ask suggestion for SB (IP) next action: after BB checks
    la = set(engine_legal_actions(gs))
    assert "check" in la
    gs = _act(gs, "check")  # BB checks on flop

    # Actor becomes SB (IP) now; query suggestion
    resp = build_suggestion(gs, actor=0)
    meta = resp.get("meta") or {}
    assert meta.get("policy_source") in {"policy", "rule"}
    # Expect table override applied on limped flop IP (present in postflop.npz)
    assert meta.get("policy_source") == "policy", f"expected table policy, got meta={meta}"
    assert not meta.get("policy_fallback", False), f"should not fallback, meta={meta}"


def test_preflop_single_raised_caller_oop_half_uses_table(monkeypatch):
    monkeypatch.setenv("SUGGEST_POLICY_DIR", "artifacts/policies")
    cfg = start_session(init_stack=200, sb=1, bb=2)
    gs = start_hand(cfg, session_id="sB", hand_id="hB1", button=0, seed=7)
    # SB opens min-raise; BB facing raise (single_raised, caller, oop, to_call>0)
    la = set(engine_legal_actions(gs))
    assert "raise" in la
    gs = _act(gs, "raise", amt=4)
    la = set(engine_legal_actions(gs))
    assert "call" in la

    resp = build_suggestion(gs, actor=1)
    meta = resp.get("meta") or {}
    assert meta.get("policy_source") in {"policy", "rule"}
    # Expect table override applied for preflop caller facing raise (covered by minimal preflop table)
    assert meta.get("policy_source") == "policy", f"expected table policy, got meta={meta}"
    assert not meta.get("policy_fallback", False), f"should not fallback, meta={meta}"
