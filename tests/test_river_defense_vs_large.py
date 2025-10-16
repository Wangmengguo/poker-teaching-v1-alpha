from poker_core.domain.actions import LegalAction
from poker_core.suggest.policy import policy_river_v1
from poker_core.suggest.types import Observation
from poker_core.suggest.types import PolicyConfig


def _obs_river(
    *,
    to_call: int,
    pot_now: int,
    hole: tuple[str, str],
    board: tuple[str, str, str, str, str],
    facing_tag: str = "two_third+",
) -> Observation:
    return Observation(
        hand_id="h_rv_defend",
        actor=0,
        street="river",
        bb=2,
        pot=pot_now,  # not used directly but included
        to_call=to_call,
        acts=[LegalAction(action="fold"), LegalAction(action="call", to_call=to_call)],
        tags=[],
        hand_class="unknown",
        table_mode="HU",
        button=0,
        spr_bucket="low",
        board_texture="na",
        ip=True,
        first_to_act=False,
        last_to_act=True,
        pot_now=pot_now,
        combo="",
        last_bet=0,
        role="na",
        range_adv=False,
        nut_adv=False,
        facing_size_tag=facing_tag,
        pot_type="single_raised",
        last_aggressor=None,
        hole=hole,
        board=board,
    )


def test_river_large_strong_value_calls_even_if_expensive():
    # Board gives three of a kind with hero's Ace: strong_value
    obs = _obs_river(
        to_call=110,
        pot_now=90,  # pot_odds ~ 0.55 (expensive)
        hole=("Ah", "As"),
        board=("Ad", "Ks", "2c", "9h", "7d"),
    )
    sug, rationale, policy, meta = policy_river_v1(obs, PolicyConfig())
    assert sug.get("action") == "call", f"Expected call with strong value vs large, got {sug}"


def test_river_large_medium_value_price_call():
    # Medium value: second pair (Q on K-high board)
    obs = _obs_river(
        to_call=48,
        pot_now=52,  # pot_odds ~ 0.48 → within default medium-call threshold
        hole=("Qd", "9s"),
        board=("Kh", "Qs", "7d", "3c", "2h"),
    )
    sug, rationale, policy, meta = policy_river_v1(obs, PolicyConfig())
    assert sug.get("action") == "call", f"Expected call for medium value at good price, got {sug}"


def test_river_large_weak_showdown_folds_bad_price():
    # Weak showdown/air: high card vs large bet at poor price should fold
    obs = _obs_river(
        to_call=80,
        pot_now=120,  # pot_odds ~ 0.40 > weak_call(0.30) → fold
        hole=("9c", "8c"),
        board=("Kh", "Qs", "7d", "3c", "2h"),
    )
    sug, rationale, policy, meta = policy_river_v1(obs, PolicyConfig())
    assert sug.get("action") == "fold", f"Expected fold with weak showdown vs large, got {sug}"
