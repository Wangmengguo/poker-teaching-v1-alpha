from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import replace

import pytest
from poker_core.domain.actions import LegalAction
from poker_core.suggest.service import POLICY_REGISTRY_V1
from poker_core.suggest.service import build_suggestion
from poker_core.suggest.types import Observation

LOGGER_NAME = "poker_core.suggest.service"


@dataclass
class _GS:
    hand_id: str = "log_hand"
    street: str = "flop"
    to_act: int = 0
    button: int = 0
    bb: int = 50
    pot: int = 300
    last_bet: int = 0
    pot_now: int = 300


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    monkeypatch.setenv("SUGGEST_POLICY_VERSION", "v1")
    monkeypatch.setenv("SUGGEST_V1_ROLLOUT_PCT", "0")


def _obs_for(street: str, acts: list[LegalAction]) -> Observation:
    return Observation(
        hand_id="hand_" + street,
        actor=0,
        street=street,
        bb=50,
        pot=300,
        to_call=0,
        acts=acts,
        tags=["pair"],
        hand_class="value_two_pair_plus",
        table_mode="HU",
        spr_bucket="ge6",
        board_texture="dry",
        ip=True,
        pot_now=300,
        combo="AhKh",
        role="pfr",
        range_adv=True,
        nut_adv=True,
        facing_size_tag="na",
        pot_type="single_raised",
    )


def test_log_contains_policy_and_rule_path(monkeypatch, caplog):
    acts = [LegalAction("bet", min=50, max=400), LegalAction("check")]
    obs = _obs_for("flop", acts)

    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", lambda gs: acts)
    monkeypatch.setattr(
        "poker_core.suggest.service.build_observation",
        lambda gs, actor, acts, annotate_fn=None, context=None: (obs, []),
    )
    monkeypatch.setattr("poker_core.suggest.service.node_key_from_observation", lambda o: "nk_rule")

    def _policy(obs_arg, cfg):
        meta = {"size_tag": "half", "rule_path": "root/line"}
        return {"action": "bet", "amount": 150}, [], "flop_v1", meta

    monkeypatch.setitem(POLICY_REGISTRY_V1, "flop", _policy)

    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    result = build_suggestion(_GS(street="flop"), actor=0)
    assert result["policy"] == "flop_v1"

    record = next(r for r in caplog.records if r.msg == "suggest_v1")
    assert record.policy_name == "flop_v1"
    assert record.street == "flop"
    assert record.action == "bet"
    assert record.size_tag == "half"
    assert record.rule_path == "root/line"
    assert record.__dict__["node_key"] == "nk_rule"
    assert record.__dict__["policy_source"] == "rules"


def test_log_mixing_and_fallback_counters(monkeypatch, caplog):
    acts = [LegalAction("bet", min=50, max=400), LegalAction("check")]
    mix_obs = _obs_for("flop", acts)

    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", lambda gs: acts)
    monkeypatch.setattr(
        "poker_core.suggest.service.build_observation",
        lambda gs, actor, acts, annotate_fn=None, context=None: (mix_obs, []),
    )
    monkeypatch.setattr("poker_core.suggest.service.node_key_from_observation", lambda o: "nk_mix")

    def _mix_policy(obs_arg, cfg):
        meta = {
            "size_tag": "third",
            "rule_path": "mix/path",
            "mix": {
                "seed_key": "mix_seed",
                "chosen_index": 1,
                "arms": [
                    {"action": "bet", "size_tag": "third", "weight": 0.7},
                    {"action": "check", "weight": 0.3},
                ],
            },
            "frequency": 0.3,
        }
        return {"action": "bet", "amount": 120}, [], "flop_v1", meta

    monkeypatch.setitem(POLICY_REGISTRY_V1, "flop", _mix_policy)
    monkeypatch.setenv("SUGGEST_MIXING", "on")

    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    caplog.clear()

    build_suggestion(_GS(street="flop"), actor=0)

    record = next(r for r in caplog.records if r.msg == "suggest_v1")
    assert record.__dict__["mix_applied"] is True
    assert record.__dict__["mix.chosen_index"] == 1

    # Trigger fallback via failing policy
    def _failing_policy(obs_arg, cfg):
        raise RuntimeError("policy failure")

    monkeypatch.setitem(POLICY_REGISTRY_V1, "flop", _failing_policy)
    caplog.clear()

    result = build_suggestion(_GS(street="flop"), actor=0)
    assert result["suggested"]["action"] in {"check", "call", "fold", "bet", "raise", "allin"}

    record_fb = next(r for r in caplog.records if r.msg == "suggest_v1")
    assert record_fb.__dict__["fallback_used"] is True
    assert record_fb.__dict__["policy_source"] == "fallback"
    assert record_fb.__dict__["mix_applied"] is False


def test_log_price_and_units_present(monkeypatch, caplog):
    acts = [LegalAction("call", to_call=100), LegalAction("fold")]
    obs = _obs_for("turn", acts)
    obs = replace(obs, to_call=100, pot=400, pot_now=400, street="turn", ip=False)

    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", lambda gs: acts)
    monkeypatch.setattr(
        "poker_core.suggest.service.build_observation",
        lambda gs, actor, acts, annotate_fn=None, context=None: (obs, []),
    )
    monkeypatch.setattr(
        "poker_core.suggest.service.node_key_from_observation", lambda o: "nk_price"
    )

    def _policy(obs_arg, cfg):
        meta = {"size_tag": "na", "rule_path": "turn/rule"}
        return {"action": "call"}, [], "turn_v1", meta

    monkeypatch.setitem(POLICY_REGISTRY_V1, "turn", _policy)

    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    result = build_suggestion(_GS(street="turn"), actor=0)
    assert result["policy"] == "turn_v1"

    record = next(r for r in caplog.records if r.msg == "suggest_v1")
    assert record.__dict__["to_call_bb"] == pytest.approx(2.0)
    assert record.__dict__["pot_odds"] == pytest.approx(100 / 500)
