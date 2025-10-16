from poker_core.domain.actions import LegalAction
from poker_core.suggest.node_key import node_key_from_observation
from poker_core.suggest.policy_loader import get_runtime_loader
from poker_core.suggest.types import Observation


def test_preflop_single_raised_caller_oop_half_hits_table(monkeypatch):
    monkeypatch.setenv("SUGGEST_POLICY_DIR", "artifacts/policies")
    loader = get_runtime_loader()
    assert loader is not None

    obs = Observation(
        hand_id="h_pf_tbl",
        actor=1,
        street="preflop",
        bb=2,
        pot=6,
        to_call=4,  # facing a raise
        acts=[
            LegalAction(action="fold"),
            LegalAction(action="call", to_call=4),
            LegalAction(action="raise", min=10, max=40),
        ],
        tags=[],
        hand_class="suited_broadway",
        table_mode="HU",
        button=0,
        spr_bucket="na",
        board_texture="na",
        ip=False,
        first_to_act=False,
        last_to_act=True,
        pot_now=6,
        combo="",
        last_bet=4,
        role="caller",
        range_adv=False,
        nut_adv=False,
        facing_size_tag="half",
        pot_type="single_raised",
        last_aggressor=0,
    )

    key = node_key_from_observation(obs)
    assert "preflop" in key and "single_raised" in key and "caller" in key and "facing=half" in key
    entry = loader.lookup(key)
    assert entry is not None, f"Expected entry for node_key={key}"
