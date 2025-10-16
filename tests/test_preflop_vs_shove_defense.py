from poker_core.domain.actions import LegalAction
from poker_core.suggest.policy import policy_preflop_v1
from poker_core.suggest.types import Observation
from poker_core.suggest.types import PolicyConfig


def _obs_vs_shove(to_call_bb: float, combo: str, bb: int = 2) -> Observation:
    to_call = int(round(to_call_bb * bb))
    # Minimal preflop facing-allin observation: only fold/call are legal
    return Observation(
        hand_id="h_pf_shove",
        actor=1,
        street="preflop",
        bb=bb,
        pot=3,  # blinds
        to_call=to_call,
        acts=[LegalAction(action="fold"), LegalAction(action="call", to_call=to_call)],
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


def test_preflop_vs_shove_le12_calls_AJs():
    obs = _obs_vs_shove(12.0, "AJs")
    sug, rationale, policy, meta = policy_preflop_v1(obs, PolicyConfig())
    assert sug.get("action") == "call", f"Expected call vs 12bb shove with AJs, got {sug}"


def test_preflop_vs_shove_18bb_calls_AQo():
    obs = _obs_vs_shove(18.0, "AQo")
    sug, rationale, policy, meta = policy_preflop_v1(obs, PolicyConfig())
    assert sug.get("action") == "call", f"Expected call vs 18bb shove with AQo, got {sug}"


def test_preflop_vs_shove_25bb_calls_AKo():
    obs = _obs_vs_shove(25.0, "AKo")
    sug, rationale, policy, meta = policy_preflop_v1(obs, PolicyConfig())
    assert sug.get("action") == "call", f"Expected call vs 25bb shove with AKo, got {sug}"


def test_preflop_vs_shove_25bb_folds_trash():
    obs = _obs_vs_shove(25.0, "A8o")
    sug, rationale, policy, meta = policy_preflop_v1(obs, PolicyConfig())
    assert sug.get("action") == "fold", f"Expected fold vs 25bb shove with weak A8o, got {sug}"
