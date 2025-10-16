import os

from poker_core.domain.actions import LegalAction
from poker_core.suggest.policy import policy_flop_v1
from poker_core.suggest.types import Observation
from poker_core.suggest.types import PolicyConfig
from poker_core.suggest.utils import HC_TOP_WEAK_OR_SECOND
from poker_core.suggest.utils import HC_WEAK_OR_AIR


def _obs_for_large_facing(
    *,
    to_call: int,
    pot_now: int,
    hand_class: str,
):
    # Minimal, focused Observation tailored for flop-facing tests
    return Observation(
        hand_id="h_test",
        actor=0,
        street="flop",
        bb=2,
        pot=4,
        to_call=to_call,
        acts=[
            LegalAction(action="fold"),
            LegalAction(action="call", to_call=to_call),
        ],
        tags=[],
        hand_class=hand_class,
        table_mode="HU",
        button=0,
        spr_bucket="low",
        board_texture="semi",
        ip=False,
        first_to_act=False,
        last_to_act=False,
        pot_now=pot_now,
        combo="",
        last_bet=0,
        role="caller",
        range_adv=False,
        nut_adv=False,
        facing_size_tag="two_third+",  # our tag for very large sizes / jams
        pot_type="single_raised",
        last_aggressor=1,
    )


def test_flop_defend_large_calls_mid_second_pairs_without_mixing():
    # Ensure deterministic behavior (no mixing)
    os.environ["SUGGEST_MIXING"] = "off"
    # Jam-like price: pot_odds ≈ 0.495 (e.g., to_call=198, pot_now=202)
    obs = _obs_for_large_facing(to_call=198, pot_now=202, hand_class=HC_TOP_WEAK_OR_SECOND)
    sug, rationale, policy, meta = policy_flop_v1(obs, PolicyConfig())
    assert (
        sug.get("action") == "call"
    ), f"Expected call vs large bet/jam with mid/second pair; got {sug}"


def test_flop_defend_large_folds_very_bad_price():
    # Pot odds very poor (0.60): should fold even with softened logic
    os.environ["SUGGEST_MIXING"] = "off"
    obs = _obs_for_large_facing(to_call=150, pot_now=100, hand_class=HC_WEAK_OR_AIR)
    sug, rationale, policy, meta = policy_flop_v1(obs, PolicyConfig())
    assert sug.get("action") == "fold", f"Expected fold when pot_odds is very high; got {sug}"
