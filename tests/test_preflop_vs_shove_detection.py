from poker_core.domain.actions import LegalAction
from poker_core.suggest.policy import policy_preflop_v1
from poker_core.suggest.types import Observation
from poker_core.suggest.types import PolicyConfig


def _obs_vs_huge_raise_with_raise_listed(to_call_bb: float, combo: str, bb: int = 2) -> Observation:
    to_call = int(round(to_call_bb * bb))
    # Some engines list a dummy 'raise' even when effectively facing a shove
    return Observation(
        hand_id="h_pf_shove_detect",
        actor=1,
        street="preflop",
        bb=bb,
        pot=3,
        to_call=to_call,
        acts=[
            LegalAction(action="fold"),
            LegalAction(action="call", to_call=to_call),
            LegalAction(action="raise", min=to_call + bb, max=to_call + 100 * bb),
        ],
        tags=[],
        hand_class="unknown",
        table_mode="HU",
        button=0,
        spr_bucket="high",
        board_texture="na",
        ip=True,
        first_to_act=False,
        last_to_act=True,
        pot_now=3,
        combo=combo,
        last_bet=0,
        role="na",
        range_adv=False,
        nut_adv=False,
        facing_size_tag="na",
        pot_type="single_raised",
        last_aggressor=None,
    )


def test_detects_shove_when_raise_present_calls_AQs():
    obs = _obs_vs_huge_raise_with_raise_listed(18.0, "AQs")
    sug, rationale, policy, meta = policy_preflop_v1(obs, PolicyConfig())
    assert (
        sug.get("action") == "call"
    ), f"Expected call vs 18bb shove-like raise with AQs, got {sug}"
