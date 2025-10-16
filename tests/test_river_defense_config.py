import json

from poker_core.domain.actions import LegalAction
from poker_core.suggest.policy import policy_river_v1
from poker_core.suggest.types import Observation
from poker_core.suggest.types import PolicyConfig


def _obs_medium_value(to_call: int, pot_now: int):
    # Qx on K-high board → medium_value by river_semantics
    return Observation(
        hand_id="h_rv_cfg",
        actor=0,
        street="river",
        bb=2,
        pot=pot_now,
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
        facing_size_tag="two_third+",
        pot_type="single_raised",
        last_aggressor=None,
        hole=("Qd", "9s"),
        board=("Kh", "Qs", "7d", "3c", "2h"),
    )


def test_river_defense_config_override(tmp_path, monkeypatch):
    # Create config that allows medium_value to call up to 0.60 pot_odds
    cfg = {"medium": {"call_le": 0.60, "mix_to": 0.62, "mix_freq": 1.0}, "weak": {"call_le": 0.35}}
    p = tmp_path / "river_defense.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("SUGGEST_RIVER_DEFENSE_FILE", str(p))

    # pot_odds ≈ 0.58 (should call under override)
    obs = _obs_medium_value(to_call=58, pot_now=42)
    sug, rationale, policy, meta = policy_river_v1(obs, PolicyConfig())
    assert sug.get("action") == "call", f"override should call at 0.58; got {sug}"
