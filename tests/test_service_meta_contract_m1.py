from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

import pytest
from poker_core.domain.actions import LegalAction
from poker_core.suggest.service import POLICY_REGISTRY_V1
from poker_core.suggest.service import build_suggestion


@dataclass
class _Player:
    stack: int = 10000
    invested: int = 0
    hole: list[str] | None = None

    def __post_init__(self) -> None:
        if self.hole is None:
            self.hole = ["Ah", "Kh"]


def _cards_for_street(street: str) -> list[str]:
    board = ["Ah", "7c", "2d", "Td", "2c"]
    if street == "flop":
        return board[:3]
    if street == "turn":
        return board[:4]
    if street == "river":
        return board[:5]
    return []


@dataclass
class _GS:
    hand_id: str = "h_meta"
    street: str = "flop"
    button: int = 0
    to_act: int = 0
    bb: int = 50
    pot: int = 300
    players: tuple[_Player, _Player] | None = None
    board: list[str] | None = None
    events: list[dict] | None = None
    last_bet: int = 0

    def __post_init__(self) -> None:
        if self.players is None:
            self.players = (_Player(), _Player())
        if self.board is None:
            self.board = _cards_for_street(self.street)
        if self.events is None:
            base = [
                {"t": "raise", "who": 0, "to": 150},
                {"t": "call", "who": 1, "amount": 150},
                {"t": "board", "street": "flop"},
            ]
            if self.street in {"turn", "river"}:
                base.append({"t": "board", "street": "turn"})
            if self.street == "river":
                base.append({"t": "board", "street": "river"})
            self.events = base


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    monkeypatch.setenv("SUGGEST_POLICY_VERSION", "v1")
    monkeypatch.setenv("SUGGEST_V1_ROLLOUT_PCT", "0")


@pytest.fixture
def patch_analysis(monkeypatch):
    def _annotate(gs, actor):
        street = str(getattr(gs, "street", "flop")).lower()
        mapping = {
            "flop": "weak_draw_or_air",
            "turn": "value_two_pair_plus",
            "river": "value_two_pair_plus",
        }
        hand_class = mapping.get(street, "value_two_pair_plus")
        return {"info": {"tags": ["pair"], "hand_class": hand_class}}

    monkeypatch.setattr(
        "poker_core.suggest.service.annotate_player_hand_from_gs",
        _annotate,
    )

    def _infer_flop(gs, actor):
        return "weak_draw_or_air"

    monkeypatch.setattr(
        "poker_core.suggest.observations.infer_flop_hand_class_from_gs",
        _infer_flop,
    )

    monkeypatch.setattr(
        "poker_core.suggest.observations._spr_bucket",
        lambda spr: "ge6",
    )

    monkeypatch.setattr(
        "poker_core.suggest.observations.derive_facing_size_tag",
        lambda *args, **kwargs: "half",
    )


@pytest.mark.parametrize("street", ["flop", "turn", "river"])
def test_meta_contains_rule_path_and_size_tag(monkeypatch, patch_analysis, street):
    acts = [LegalAction("bet", min=50, max=1000), LegalAction("check")]

    def _legal_actions(_):
        return acts

    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", _legal_actions)

    gs = _GS(street=street, to_act=0)
    result = build_suggestion(gs, actor=0)

    assert result["policy"] == f"{street}_v1"
    meta = result.get("meta") or {}
    assert isinstance(meta.get("rule_path"), str) and meta["rule_path"].strip()
    assert isinstance(meta.get("size_tag"), str) and meta["size_tag"].strip()
    if street == "flop":
        assert isinstance(meta.get("plan"), str) and meta["plan"].strip()


@pytest.mark.parametrize(
    "freq, expected",
    [
        (0.27, "27%"),
        ("80%", "80%"),
        (0.0, "0%"),
    ],
)
def test_explanations_render_frequency_when_present(monkeypatch, patch_analysis, freq, expected):
    acts = [LegalAction("call", to_call=100), LegalAction("fold")]

    def _legal_actions(_):
        return acts

    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", _legal_actions)

    def _stub_policy(obs, cfg):
        rationale = [
            {
                "code": "FL_MDF_DEFEND",
                "data": {"mdf": 0.66, "pot_odds": 0.34, "facing": "half"},
            }
        ]
        meta = {"mdf": 0.66, "pot_odds": 0.34, "size_tag": "half", "frequency": freq}
        return {"action": "call"}, rationale, "flop_v1", meta

    monkeypatch.setitem(POLICY_REGISTRY_V1, "flop", _stub_policy)

    gs = _GS(street="flop", to_act=1, last_bet=100)
    result = build_suggestion(gs, actor=1)

    exp = result.get("explanations") or []
    freq_lines = [line for line in exp if "频率" in line]
    assert freq_lines, exp
    combined = " ".join(freq_lines)
    assert expected in combined
    assert any(keyword in combined for keyword in ("建议频率", "大多数", "极少", "偶尔"))


@pytest.mark.parametrize(
    "freq, expected_bits",
    [
        (Fraction(1, 3), ["33%", "偶尔"]),
        (Decimal("0.71"), ["71%", "大多数"]),
        (Fraction(1, 250), ["<1%", "极少"]),
    ],
)
def test_describe_frequency_supports_rationals_and_decimals(freq, expected_bits):
    from poker_core.suggest.service import _describe_frequency

    rendered = _describe_frequency(freq)
    assert rendered is not None
    for bit in expected_bits:
        assert bit in rendered


def test_describe_frequency_ignores_unparsable_text():
    from poker_core.suggest.service import _describe_frequency

    assert _describe_frequency("n/a") is None


def test_turn_rule_path_appends_facing_context(monkeypatch, patch_analysis):
    acts = [
        LegalAction("call", to_call=100),
        LegalAction("raise", min=200, max=400),
        LegalAction("fold"),
    ]

    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", lambda gs: acts)

    gs = _GS(street="turn", to_act=1, last_bet=100, pot=500)
    result = build_suggestion(gs, actor=1)

    meta = result.get("meta") or {}
    assert meta.get("facing_size_tag") == "half"
    assert meta.get("rule_path", "").endswith("/facing:half")
