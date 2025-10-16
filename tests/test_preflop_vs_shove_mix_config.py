import json

from poker_core.domain.actions import LegalAction
from poker_core.suggest.policy import policy_preflop_v1
from poker_core.suggest.types import Observation
from poker_core.suggest.types import PolicyConfig


def _obs_vs_shove(to_call_bb: float, combo: str, bb: int = 2) -> Observation:
    to_call = int(round(to_call_bb * bb))
    return Observation(
        hand_id="h_mix_cfg",
        actor=1,
        street="preflop",
        bb=bb,
        pot=3,
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


def test_preflop_vs_shove_mix_map_override(tmp_path, monkeypatch):
    # Prepare a custom vs-shove config that forces KQs to always call in le12 band
    cfg = {
        "le12": {"call": [], "mix": ["KQs"], "mix_map": {"KQs": 1.0}},
        "13to20": {"call": [], "mix": []},
        "gt20": {"call": [], "mix": []},
    }
    d = tmp_path / "cfg"
    d.mkdir()
    with open(d / "preflop_vs_shove_HU.json", "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    monkeypatch.setenv("SUGGEST_CONFIG_DIR", str(d))
    monkeypatch.setenv("SUGGEST_MIXING", "on")

    obs = _obs_vs_shove(12.0, "KQs")
    sug, rationale, policy, meta = policy_preflop_v1(obs, PolicyConfig())
    assert sug.get("action") == "call", f"mix_map=1.0 should force call; got {sug}"
