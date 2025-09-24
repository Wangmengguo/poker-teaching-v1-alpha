from poker_core.domain.actions import LegalAction
from poker_core.suggest.service import (
    POLICY_REGISTRY,
    POLICY_REGISTRY_V1,
    build_suggestion,
)


def test_service_clamps_bet_and_reports_warn_clamped(monkeypatch):
    # 通过公开入口：stub 合法动作与策略返回的越界金额
    acts = [LegalAction(action="bet", min=100, max=300)]

    def _legal_actions(_):
        return acts

    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", _legal_actions)
    monkeypatch.setenv("SUGGEST_POLICY_VERSION", "v1")

    def _stub_policy(obs, cfg):
        return {"action": "bet", "amount": 500}, [], "flop_stub"

    monkeypatch.setitem(POLICY_REGISTRY_V1, "flop", _stub_policy)

    gs = _DummyGS()
    gs.street = "flop"
    gs.to_act = 0

    result = build_suggestion(gs, actor=0)

    assert result["suggested"]["amount"] == 300
    codes = {r.get("code") for r in result.get("rationale", [])}
    assert "W_CLAMPED" in codes
    clamp_items = [r for r in result["rationale"] if r.get("code") == "W_CLAMPED"]
    assert clamp_items
    info = clamp_items[-1].get("data") or clamp_items[-1].get("meta") or {}
    assert info.get("min") == 100
    assert info.get("max") == 300
    assert info.get("given") == 500
    assert info.get("chosen") == 300


def test_policy_registry_contains_all_streets():
    for k in ("preflop", "flop", "turn", "river"):
        assert k in POLICY_REGISTRY


class _DummyGS:
    def __init__(self):
        self.hand_id = "h_x"
        self.street = "flop"
        self.bb = 50
        self.pot = 0
        self.to_act = 0


def test_build_suggestion_injects_warning_on_analysis_failure(monkeypatch):
    # 强制 analysis 抛错，且通过公开入口 build_suggestion 断言预警注入
    import poker_core.suggest.service as svc

    def _boom(gs, actor):
        raise RuntimeError("no hole cards")

    monkeypatch.setattr(svc, "annotate_player_hand_from_gs", _boom)

    acts = [LegalAction(action="check")]

    def _legal_actions(_):
        return acts

    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", _legal_actions)

    gs = _DummyGS()
    gs.street = "flop"
    gs.to_act = 0

    result = build_suggestion(gs, actor=0)
    codes = {r.get("code") for r in result.get("rationale", [])}
    assert "W_ANALYSIS" in codes
