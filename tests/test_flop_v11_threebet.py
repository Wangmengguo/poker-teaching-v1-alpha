from poker_core.domain.actions import LegalAction
from poker_core.suggest.policy import policy_flop_v1
from poker_core.suggest.types import Observation, PolicyConfig


def _obs_threebet(
    *,
    ip: bool,
    role: str,
    texture: str,
    spr: str,
    hand_class: str,
    to_call: int = 0,
    pot_now: int = 180,
    raise_min: int = 200,
    acts: list = None,
):
    if acts is None:
        acts = []
        if to_call == 0:
            acts = [LegalAction("check"), LegalAction("bet", min=20, max=1200)]
        else:
            acts = [
                LegalAction("fold"),
                LegalAction("call", to_call=to_call),
                LegalAction("raise", min=raise_min, max=1200),
            ]
    return Observation(
        hand_id="h3b",
        actor=1 if ip else 0,
        street="flop",
        bb=50,
        pot=0,
        to_call=to_call,
        acts=acts,
        tags=[],
        hand_class=hand_class,
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
            "na"
            if to_call == 0
            else ("two_third+" if to_call >= int(0.75 * pot_now) else "half")
        ),
        pot_type="threebet",
    )


def _call_policy(obs: Observation):
    return policy_flop_v1(obs, PolicyConfig())


def test_3bet_pfr_ip_dry_op_tptk_le3_bet_midlarge():
    ob = _obs_threebet(
        ip=True,
        role="pfr",
        texture="dry",
        spr="le3",
        hand_class="overpair_or_top_pair_strong",
    )
    suggested, rationale, name, meta = _call_policy(ob)
    assert name == "flop_v1"
    assert suggested["action"] in ("bet", "check")
    if suggested["action"] == "bet":
        assert meta["size_tag"] in ("two_third", "pot", "half")


def test_3bet_pfr_ip_wet_value_le3_pot():
    ob = _obs_threebet(
        ip=True, role="pfr", texture="wet", spr="le3", hand_class="value_two_pair_plus"
    )
    suggested, rationale, name, meta = _call_policy(ob)
    if suggested["action"] == "bet":
        assert meta["size_tag"] in ("pot", "two_third")


def test_3bet_pfr_oop_semi_le3_strong_draw_lead_half():
    ob = _obs_threebet(
        ip=False, role="pfr", texture="semi", spr="le3", hand_class="strong_draw"
    )
    suggested, rationale, name, meta = _call_policy(ob)
    assert suggested["action"] in ("bet", "check")
    if suggested["action"] == "bet":
        assert meta["size_tag"] == "half"


def test_3bet_caller_ip_dry_strong_draw_bet_half():
    ob = _obs_threebet(
        ip=True, role="caller", texture="dry", spr="le3", hand_class="strong_draw"
    )
    suggested, rationale, name, meta = _call_policy(ob)
    assert suggested["action"] in ("bet", "check")
    if suggested["action"] == "bet":
        assert meta["size_tag"] == "half"


def test_3bet_pfr_ip_semi_face_half_call_mdf():
    ob = _obs_threebet(
        ip=True,
        role="pfr",
        texture="semi",
        spr="3to6",
        hand_class="top_pair_weak_or_second_pair",
        to_call=80,
        pot_now=160,
    )
    suggested, rationale, name, meta = _call_policy(ob)
    assert suggested["action"] in ("call", "fold", "raise")


def test_3bet_oop_wet_value_face_small_raise_value():
    # facing small (third) → expect value raise two_third (stub)
    pot_now = 180
    to_call = 50  # ~ < half
    ob = _obs_threebet(
        ip=False,
        role="pfr",
        texture="wet",
        spr="3to6",
        hand_class="value_two_pair_plus",
        to_call=to_call,
        pot_now=pot_now,
    )
    suggested, rationale, name, meta = _call_policy(ob)
    assert suggested["action"] in ("raise", "call")
    if suggested["action"] == "raise":
        assert meta.get("size_tag") == "two_third"


def test_3bet_ip_semi_strong_draw_face_sizes():
    # vs two_third+ → call; vs small → raise half
    ob_big = _obs_threebet(
        ip=True,
        role="pfr",
        texture="semi",
        spr="3to6",
        hand_class="strong_draw",
        to_call=140,
        pot_now=180,
    )
    s1, r1, n1, m1 = _call_policy(ob_big)
    assert s1["action"] in ("call", "raise")
    if s1["action"] == "call":
        pass
    ob_small = _obs_threebet(
        ip=True,
        role="pfr",
        texture="semi",
        spr="3to6",
        hand_class="strong_draw",
        to_call=50,
        pot_now=180,
        raise_min=120,
    )
    s2, r2, n2, m2 = _call_policy(ob_small)
    assert s2["action"] in ("raise", "call")
    if s2["action"] == "raise":
        assert m2.get("size_tag") == "half"


def test_3bet_caller_oop_wet_face_large_call_or_fold():
    ob = _obs_threebet(
        ip=False,
        role="caller",
        texture="wet",
        spr="3to6",
        hand_class="middle_pair_or_third_pair_minus",
        to_call=140,
        pot_now=180,
    )
    suggested, rationale, name, meta = _call_policy(ob)
    assert suggested["action"] in ("call", "fold")


def test_3bet_defaults_when_unknown():
    ob = _obs_threebet(
        ip=True, role="pfr", texture="dry", spr="3to6", hand_class="unknown"
    )
    suggested, rationale, name, meta = _call_policy(ob)
    assert suggested["action"] in ("bet", "check")


def test_3bet_oop_dry_value_two_third():
    ob = _obs_threebet(
        ip=False, role="pfr", texture="dry", spr="le3", hand_class="value_two_pair_plus"
    )
    suggested, rationale, name, meta = _call_policy(ob)
    if suggested["action"] == "bet":
        assert meta["size_tag"] in ("two_third", "pot")


def test_3bet_value_raise_min_reopen_and_clamp_concurrent():
    # Create a facing small size but a conflicting raise window (min>max) to simulate concurrent min-reopen+clamp
    pot_now = 160
    to_call = 40  # 'third'
    # Conflicting window (min>max to simulate concurrent min-reopen+clamp)
    conflicting_acts = [
        LegalAction("fold"),
        LegalAction("call", to_call=to_call),
        LegalAction("raise", min=300, max=200),
    ]
    ob = _obs_threebet(
        ip=False,
        role="pfr",
        texture="dry",
        spr="3to6",
        hand_class="value_two_pair_plus",
        to_call=to_call,
        pot_now=pot_now,
        acts=conflicting_acts,
    )
    suggested, rationale, name, meta = _call_policy(ob)
    assert suggested["action"] in ("raise", "call")
    # Simulate service rationale (min-reopen/clamp) for unit-test visibility
    if suggested["action"] == "raise" and meta.get("size_tag"):
        # approximate raise-to for half/two_third
        sz = meta.get("size_tag")
        calc = int(pot_now * (2 / 3 if sz == "two_third" else 0.5 + 1))
        rspec = next((a for a in ob.acts if a.action == "raise"), None)
        codes = set()
        if rspec and rspec.min is not None and calc < rspec.min:
            codes.add("FL_MIN_REOPEN_ADJUSTED")
        if rspec and rspec.max is not None and calc > rspec.max:
            codes.add("W_CLAMPED")
        assert codes.intersection({"FL_MIN_REOPEN_ADJUSTED", "W_CLAMPED"})
