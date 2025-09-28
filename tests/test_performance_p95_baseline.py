from __future__ import annotations

import math
import time
from dataclasses import dataclass
from dataclasses import replace

import pytest
from poker_core.domain.actions import LegalAction
from poker_core.suggest.service import build_suggestion
from poker_core.suggest.types import Observation


@dataclass
class _GS:
    hand_id: str
    street: str
    to_act: int
    bb: int
    pot: int
    last_bet: int
    pot_now: int


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[idx]


@pytest.mark.slow
def test_performance_p95_baseline(monkeypatch):
    monkeypatch.setenv("SUGGEST_POLICY_VERSION", "v1")
    monkeypatch.setenv("SUGGEST_V1_ROLLOUT_PCT", "0")
    monkeypatch.setenv("SUGGEST_MIXING", "off")

    samples: list[tuple[_GS, Observation, list[LegalAction]]] = []
    streets = ["preflop", "flop", "turn", "river"]

    for idx in range(100):
        street = streets[idx % len(streets)]
        to_call = 0 if street in {"preflop", "flop"} else 50
        pot = 300 + idx * 5
        pot_now = pot
        hand_id = f"perf_{idx}"
        acts: list[LegalAction]
        if street == "preflop":
            acts = [
                LegalAction("raise", min=150, max=400),
                LegalAction("call", to_call=to_call or 100),
                LegalAction("fold"),
            ]
        elif street == "river":
            acts = [
                LegalAction("bet", min=150, max=600),
                LegalAction("check"),
                LegalAction("fold"),
            ]
        else:
            acts = [
                LegalAction("bet", min=150, max=500),
                LegalAction("check"),
            ]

        obs = Observation(
            hand_id=hand_id,
            actor=0,
            street=street,
            bb=50,
            pot=pot,
            to_call=to_call,
            acts=acts,
            tags=["pair"],
            hand_class="value_two_pair_plus" if street != "preflop" else "premium_pair",
            table_mode="HU",
            spr_bucket="ge6",
            board_texture="dry" if street in {"flop", "turn"} else "na",
            ip=bool(idx % 2),
            pot_now=pot_now,
            combo="AhKh",
            last_bet=to_call,
            role="pfr",
            range_adv=street in {"flop", "turn"},
            nut_adv=street in {"flop", "turn"},
            facing_size_tag="half" if street in {"turn", "river"} else "na",
            pot_type="single_raised",
        )

        gs = _GS(
            hand_id=hand_id,
            street=street,
            to_act=0,
            bb=50,
            pot=pot,
            last_bet=to_call,
            pot_now=pot_now,
        )
        samples.append((gs, obs, acts))

    hand_to_obs: dict[str, Observation] = {gs.hand_id: obs for gs, obs, _ in samples}
    hand_to_acts: dict[str, list[LegalAction]] = {gs.hand_id: acts for gs, _, acts in samples}

    def _fake_legal_actions(gs):
        return hand_to_acts[gs.hand_id]

    def _fake_build_observation(gs, actor, acts, annotate_fn=None, context=None):
        obs = hand_to_obs[gs.hand_id]
        # Refresh mutable acts reference for downstream usage.
        return replace(obs, acts=list(acts)), []

    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", _fake_legal_actions)
    monkeypatch.setattr("poker_core.suggest.service.build_observation", _fake_build_observation)

    durations: list[float] = []

    for gs, _, acts in samples:
        start = time.perf_counter()
        result = build_suggestion(gs, actor=0)
        end = time.perf_counter()
        durations.append(end - start)
        assert result["suggested"]["action"] in {a.action for a in acts}

    cold_count = max(5, len(durations) // 10)
    cold_p95 = _p95(durations[:cold_count])
    warm_p95 = _p95(durations[cold_count:])

    assert cold_p95 <= 1.0
    assert warm_p95 <= 1.0
