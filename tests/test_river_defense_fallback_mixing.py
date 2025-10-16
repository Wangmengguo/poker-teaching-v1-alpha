from poker_core.domain.actions import LegalAction
from poker_core.suggest.policy import policy_river_v1
from poker_core.suggest.types import Observation
from poker_core.suggest.types import PolicyConfig


def _obs_medium_value_mix_window():
    # pot_odds ~ 0.51 falls into (call_le=0.50, mix_to=0.52]
    return Observation(
        hand_id="h_rv_fallback_mix",
        actor=0,
        street="river",
        bb=2,
        pot=0,
        to_call=51,
        acts=[LegalAction(action="fold"), LegalAction(action="call", to_call=51)],
        tags=[],
        hand_class="unknown",
        table_mode="HU",
        button=0,
        spr_bucket="low",
        board_texture="na",
        ip=True,
        first_to_act=False,
        last_to_act=True,
        pot_now=49,  # 51/(49+51)=0.51
        combo="",
        last_bet=0,
        role="na",
        range_adv=False,
        nut_adv=False,
        facing_size_tag="two_third+",
        pot_type="single_raised",
        last_aggressor=None,
        hole=("Qd", "9s"),
        board=("Kh", "Qs", "7d", "3c", "2h"),
    )


def test_river_fallback_mixing_no_unboundlocalerror(monkeypatch):
    # Ensure mixing is on
    monkeypatch.setenv("SUGGEST_MIXING", "on")
    # Remove file overrides to go through fallback path safely
    monkeypatch.delenv("SUGGEST_RIVER_DEFENSE_FILE", raising=False)

    obs = _obs_medium_value_mix_window()
    sug, rationale, policy, meta = policy_river_v1(obs, PolicyConfig())

    # No exception should be raised; action should be call or fold depending on mix
    assert sug.get("action") in {"call", "fold"}
