import pytest
from poker_core.domain.actions import LegalAction
from poker_core.suggest.policy import policy_flop_v1
from poker_core.suggest.types import Observation, PolicyConfig


def _obs_limped(ip: bool, texture: str, spr: str, hand_class: str):
    acts = [LegalAction("check"), LegalAction("bet", min=10, max=500)]
    return Observation(
        hand_id="h",
        actor=1 if ip else 0,
        street="flop",
        bb=50,
        pot=100,
        to_call=0,
        acts=acts,
        tags=[],
        hand_class=hand_class,
        table_mode="HU",
        spr_bucket=spr,
        board_texture=texture,
        ip=ip,
        pot_now=100,
        combo="",
        role="na",
        range_adv=False,
        nut_adv=False,
        facing_size_tag="na",
        pot_type="limped",
    )


@pytest.mark.parametrize(
    "ip,texture,spr,hand_class",
    [
        (True, "dry", "3to6", "weak_draw_or_air"),
        (True, "semi", "le3", "strong_draw"),
        (True, "wet", "le3", "value_two_pair_plus"),
        (False, "semi", "le3", "strong_draw"),
        (False, "wet", "le3", "value_two_pair_plus"),
        (False, "dry", "3to6", "middle_pair_or_third_pair_minus"),
    ],
)
def test_limped_smoke(ip, texture, spr, hand_class):
    ob = _obs_limped(ip, texture, spr, hand_class)
    suggested, rationale, name, meta = policy_flop_v1(ob, PolicyConfig())
    assert name == "flop_v1"
    assert suggested["action"] in ("bet", "check")
    # when value on wet+le3, prefer bet pot for IP/OOP
    if texture == "wet" and spr == "le3" and hand_class == "value_two_pair_plus":
        assert meta.get("size_tag") in ("two_third", "pot")
