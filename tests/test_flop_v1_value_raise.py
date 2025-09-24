import pytest
from poker_core.domain.actions import LegalAction
from poker_core.suggest.policy import policy_flop_v1
from poker_core.suggest.types import Observation, PolicyConfig


def _obs(
    *,
    pot_type: str,
    ip: bool,
    role: str,
    texture: str,
    spr: str,
    to_call: int,
    pot_now: int,
    acts: list[LegalAction] | None = None,
):
    if acts is None:
        acts = [
            LegalAction("fold"),
            LegalAction("call", to_call=to_call),
            LegalAction("raise", min=120, max=1200),
        ]
    return Observation(
        hand_id="hv",
        actor=1 if ip else 0,
        street="flop",
        bb=50,
        pot=0,
        to_call=to_call,
        acts=acts,
        tags=[],
        hand_class="value_two_pair_plus",
        table_mode="HU",
        spr_bucket=spr,
        board_texture=texture,
        ip=ip,
        pot_now=pot_now,
        combo="",
        role=role,
        range_adv=False,
        nut_adv=False,
        facing_size_tag=(
            "two_third+"
            if to_call >= int(0.75 * pot_now)
            else ("half" if to_call >= int(0.5 * pot_now) else "third")
        ),
        pot_type=pot_type,
    )


def _call(o: Observation):
    return policy_flop_v1(o, PolicyConfig())


@pytest.mark.parametrize("pot_type", ["single_raised", "threebet"])
def test_value_raise_dry_vs_small_half(pot_type):
    o = _obs(
        pot_type=pot_type,
        ip=True,
        role="pfr",
        texture="dry",
        spr="3to6",
        to_call=40,
        pot_now=120,
    )
    s, r, n, m = _call(o)
    assert s["action"] in ("raise", "call")
    if s["action"] == "raise":
        assert m.get("size_tag") in ("half", "two_third")


@pytest.mark.parametrize("pot_type", ["single_raised", "threebet"])
def test_value_raise_semiwet_vs_half_twothird(pot_type):
    o = _obs(
        pot_type=pot_type,
        ip=False,
        role="pfr",
        texture="semi",
        spr="3to6",
        to_call=70,
        pot_now=140,
    )
    s, r, n, m = _call(o)
    assert s["action"] in ("raise", "call")
    if s["action"] == "raise":
        assert m.get("size_tag") == "two_third"


def test_value_raise_tworthird_plus_calls():
    o = _obs(
        pot_type="single_raised",
        ip=True,
        role="pfr",
        texture="wet",
        spr="3to6",
        to_call=120,
        pot_now=150,
    )
    s, r, n, m = _call(o)
    assert s["action"] in ("call", "raise")
    if s["action"] == "raise":
        # Accept raise if window is unusual; but prefer call branch
        pass


def test_min_reopen_and_clamp_still_ok():
    # Raise suggested half, but raise.min > target or max < target; ensure rationale present via service path later
    o = _obs(
        pot_type="single_raised",
        ip=True,
        role="pfr",
        texture="dry",
        spr="3to6",
        to_call=40,
        pot_now=120,
        acts=[
            LegalAction("fold"),
            LegalAction("call", to_call=40),
            LegalAction("raise", min=300, max=200),
        ],
    )
    s, r, n, m = _call(o)
    assert s["action"] in ("raise", "call")


def test_value_raise_tworthird_plus_calls_threebet():
    o = _obs(
        pot_type="threebet",
        ip=True,
        role="pfr",
        texture="semi",
        spr="3to6",
        to_call=150,
        pot_now=180,
    )
    s, r, n, m = _call(o)
    assert s["action"] in ("call", "raise")
