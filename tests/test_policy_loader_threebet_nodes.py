from poker_core.domain.actions import LegalAction
from poker_core.suggest.node_key import node_key_from_observation
from poker_core.suggest.policy_loader import get_runtime_loader
from poker_core.suggest.types import Observation


def test_threebet_postflop_lookup_hits_loader(monkeypatch):
    monkeypatch.setenv("SUGGEST_POLICY_DIR", "artifacts/policies")
    loader = get_runtime_loader()
    assert loader is not None, "Policy loader should initialise with artifacts/policies"

    # Build an observation that maps to a threebet flop node we created by augmentation
    obs = Observation(
        hand_id="h_tb",
        actor=1,
        street="flop",
        bb=2,
        pot=12,
        to_call=4,
        acts=[
            LegalAction(action="fold"),
            LegalAction(action="call", to_call=4),
            LegalAction(action="raise", min=12, max=40),
        ],
        tags=[],
        hand_class="overpair_or_tptk",
        table_mode="HU",
        button=0,
        spr_bucket="spr4",
        board_texture="dry",
        ip=True,
        first_to_act=False,
        last_to_act=True,
        pot_now=12,
        combo="",
        last_bet=4,
        role="pfr",
        range_adv=True,
        nut_adv=False,
        facing_size_tag="half",
        pot_type="threebet",
        last_aggressor=0,
    )

    key = node_key_from_observation(obs)
    assert "threebet" in key and "flop" in key and "facing=half" in key
    entry = loader.lookup(key)
    assert entry is not None, f"Expected a policy entry for node_key={key}"
