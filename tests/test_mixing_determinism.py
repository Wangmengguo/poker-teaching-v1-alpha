import math
from collections import Counter

import pytest
from poker_core.domain.actions import LegalAction
from poker_core.suggest.context import SuggestContext
from poker_core.suggest.policy import policy_flop_v1
from poker_core.suggest.service import build_suggestion
from poker_core.suggest.types import Observation
from poker_core.suggest.types import PolicyConfig
from poker_core.suggest.utils import stable_weighted_choice


@pytest.fixture
def mixed_rules(monkeypatch):
    rules = {
        "single_raised": {
            "role": {
                "pfr": {
                    "ip": {
                        "dry": {
                            "ge6": {
                                "value_two_pair_plus": {
                                    "mix": [
                                        {"action": "bet", "size_tag": "third", "weight": 0.7},
                                        {"action": "check", "weight": 0.2},
                                        {"action": "bet", "size_tag": "half", "weight": 0.1},
                                    ],
                                    "plan": "计划描述",
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    monkeypatch.setattr("poker_core.suggest.policy.get_flop_rules", lambda: (rules, 1))
    return rules


def _make_obs(acts: list[LegalAction]) -> Observation:
    return Observation(
        hand_id="mix_hand",
        actor=0,
        street="flop",
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
        context=SuggestContext.build(),
    )


def test_stable_weighted_choice_deterministic():
    weights = [0.15, 0.35, 0.5]
    key = "hand123:node_xyz"
    first = stable_weighted_choice(key, weights)
    second = stable_weighted_choice(key, weights)
    assert first == second


def test_distribution_approx_matches_weights():
    weights = [0.1, 0.3, 0.6]
    total_trials = 4096
    counts: Counter[int] = Counter()
    for i in range(total_trials):
        seed = f"hand_{i}:node"
        idx = stable_weighted_choice(seed, weights)
        counts[idx] += 1

    total = sum(counts.values())
    assert total == total_trials
    weight_sum = sum(weights)
    for idx, weight in enumerate(weights):
        expected = weight / weight_sum
        observed = counts[idx] / total
        assert math.isclose(observed, expected, rel_tol=0.12, abs_tol=0.03)


def test_mixing_off_chooses_max_weight(monkeypatch, mixed_rules):
    monkeypatch.setenv("SUGGEST_MIXING", "off")
    acts = [LegalAction("bet", min=50, max=400), LegalAction("check")]
    obs = _make_obs(acts)

    suggested, rationale, policy_name, meta = policy_flop_v1(obs, PolicyConfig())
    assert policy_name == "flop_v1"
    assert suggested["action"] == "bet"
    assert meta.get("size_tag") == "third"
    assert "frequency" not in meta
    assert "mix" not in meta


def test_meta_mix_and_frequency_emitted(monkeypatch, mixed_rules):
    monkeypatch.setenv("SUGGEST_MIXING", "on")
    monkeypatch.setenv("SUGGEST_POLICY_VERSION", "v1")
    monkeypatch.setenv("SUGGEST_DEBUG", "1")

    acts = [LegalAction("bet", min=50, max=400), LegalAction("check")]

    def _fake_legal_actions(gs):
        return acts

    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", _fake_legal_actions)

    obs = _make_obs(acts)

    def _fake_build_observation(gs, actor, acts_from_service, annotate_fn=None, context=None):
        return obs, []

    monkeypatch.setattr("poker_core.suggest.service.build_observation", _fake_build_observation)

    class _GS:
        hand_id = "mix_hand"
        street = "flop"
        to_act = 0
        button = 0
        bb = 50
        pot = 300
        last_bet = 0

    result = build_suggestion(_GS(), actor=0)

    meta = result.get("meta") or {}
    assert meta.get("frequency") is not None
    mix_info = ((result.get("debug") or {}).get("meta") or {}).get("mix")
    assert isinstance(mix_info, dict)
    assert "arms" in mix_info and isinstance(mix_info["arms"], list)
    chosen = mix_info.get("chosen_index")
    assert isinstance(chosen, int)
    arms = mix_info["arms"]
    assert 0 <= chosen < len(arms)
    chosen_weight = arms[chosen]["weight"]
    assert math.isclose(meta["frequency"], chosen_weight, rel_tol=1e-6, abs_tol=1e-6)
    seed_key = mix_info.get("seed_key")
    assert isinstance(seed_key, str) and seed_key
    node_key = meta.get("node_key")
    assert isinstance(node_key, str) and node_key.startswith("flop|single_raised|pfr|ip|")
    assert isinstance(meta.get("rule_path"), str)


def test_mixing_on_check_clears_size_tag(monkeypatch, mixed_rules):
    monkeypatch.setenv("SUGGEST_MIXING", "on")
    acts = [LegalAction("bet", min=50, max=400), LegalAction("check")]
    obs = _make_obs(acts)

    monkeypatch.setattr(
        "poker_core.suggest.policy.stable_weighted_choice",
        lambda key, weights: 1,
    )

    suggested, rationale, policy_name, meta = policy_flop_v1(obs, PolicyConfig())

    assert policy_name == "flop_v1"
    assert suggested["action"] == "check"
    assert meta.get("size_tag") is None
