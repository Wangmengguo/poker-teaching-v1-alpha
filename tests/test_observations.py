from __future__ import annotations

import pytest
from poker_core.domain.actions import LegalAction


class _Player:
    def __init__(self, *, stack=1000, invested_street=0, hole=None):
        self.stack = stack
        self.invested_street = invested_street
        self.hole = hole or []


class _GS:
    def __init__(
        self,
        *,
        hand_id="h_1",
        session_id="s_1",
        street="preflop",
        button=0,
        to_act=0,
        bb=50,
        pot=150,
        players=None,
        board=None,
        range_token=None,
    ):
        self.hand_id = hand_id
        self.session_id = session_id
        self.street = street
        self.button = button
        self.to_act = to_act
        self.bb = bb
        self.pot = pot
        self.board = board or []
        self.players = players or (_Player(), _Player())
        self.range_token = range_token


@pytest.fixture
def fake_annotation(monkeypatch):
    def _annotate(gs, actor):
        return {"info": {"tags": ["suited_broadway"], "hand_class": "AKs"}}

    monkeypatch.setattr(
        "poker_core.suggest.observations.annotate_player_hand_from_gs",
        _annotate,
    )


def test_build_preflop_observation_basic(monkeypatch, fake_annotation):
    from poker_core.suggest.observations import build_preflop_observation

    p0 = _Player(stack=9000, invested_street=50, hole=["Ah", "Kh"])
    p1 = _Player(stack=9000, invested_street=100)
    gs = _GS(street="preflop", button=1, to_act=0, bb=50, pot=150, players=(p0, p1))

    acts = [
        LegalAction(action="fold"),
        LegalAction(action="call", to_call=50),
        LegalAction(action="raise", min=150, max=450),
    ]

    obs, pre_rationale = build_preflop_observation(gs, actor=0, acts=acts)

    assert obs.street == "preflop"
    assert obs.to_call == 50
    # pot_now = pot + sum invested_street (50 + 100)
    assert obs.pot_now == 300
    # combo from hole cards should be suited AKs
    assert obs.combo == "AKs"
    # SB preflop 为 OOP: button=1 -> actor 0 是 SB
    assert obs.ip is False
    assert obs.table_mode == "HU"
    assert obs.tags == ["suited_broadway"]
    assert obs.hand_class == "AKs"
    assert getattr(obs, "hand_strength", None) is not None
    assert obs.hand_strength.street == "preflop"
    assert obs.hand_strength.label == "preflop_suited_broadway"
    assert pre_rationale == []


def test_build_flop_observation_derives_advantages(monkeypatch, fake_annotation):
    from poker_core.suggest.observations import build_flop_observation

    p0 = _Player(stack=8000, invested_street=200, hole=["Ah", "Kh"])
    p1 = _Player(stack=7500, invested_street=400)
    gs = _GS(
        street="flop",
        button=0,
        to_act=0,  # 观察有强牌的玩家（p0）
        bb=50,
        pot=600,
        players=(p0, p1),
        board=["Ad", "7c", "2d"],
    )

    acts = [
        LegalAction(action="fold"),
        LegalAction(action="call", to_call=150),
        LegalAction(action="raise", min=450, max=900),
    ]

    calls = []

    def _classify(board):
        return {"texture": "dry"}

    def _range_adv(texture, role):
        calls.append(("range", texture, role))
        return True

    def _nut_adv(texture, role):
        calls.append(("nut", texture, role))
        return False

    monkeypatch.setattr(
        "poker_core.suggest.observations.classify_flop",
        _classify,
    )
    monkeypatch.setattr(
        "poker_core.suggest.observations.range_advantage",
        _range_adv,
    )
    monkeypatch.setattr(
        "poker_core.suggest.observations.nut_advantage",
        _nut_adv,
    )

    obs, pre_rationale = build_flop_observation(gs, actor=0, acts=acts)  # 观察有强牌的玩家

    assert obs.street == "flop"
    assert obs.board_texture == "dry"
    assert obs.to_call == 150
    assert obs.pot_now == 1200  # pot + invested (200 + 400)
    # 无事件推断 PFR 时，不再用按钮回退，role 保持为未知
    assert obs.role == "na"
    # last_aggressor 在此场景通常为 None（未提供事件流）
    assert getattr(obs, "last_aggressor", None) is None
    assert obs.range_adv is True
    assert obs.nut_adv is False
    assert obs.facing_size_tag in {"third", "half", "two_third+", "na"}
    assert obs.hand_strength.street == "flop"
    assert obs.hand_strength.label == "flop_top_pair_or_overpair"
    assert pre_rationale == []

    # 确认优势函数被调用
    assert ("range", "dry", obs.role) in calls
    assert ("nut", "dry", obs.role) in calls


def test_flop_action_order_flags(monkeypatch, fake_annotation):
    from poker_core.suggest.observations import build_flop_observation

    p0 = _Player(stack=8000, invested_street=200, hole=["Ah", "Kh"])
    p1 = _Player(stack=7500, invested_street=400)
    gs = _GS(
        street="flop",
        button=0,
        to_act=1,
        bb=50,
        pot=600,
        players=(p0, p1),
        board=["Ad", "7c", "2d"],
    )

    acts = [
        LegalAction(action="check"),
        LegalAction(action="call", to_call=150),
        LegalAction(action="raise", min=450, max=900),
    ]

    # actor=1：flop 非按钮先行动 → 非 IP、first_to_act=True、last_to_act=False
    obs1, _ = build_flop_observation(gs, actor=1, acts=acts)
    assert obs1.ip is False
    assert getattr(obs1, "first_to_act", False) is True
    assert getattr(obs1, "last_to_act", False) is False

    # actor=0：flop 按钮后行动 → IP、first_to_act=False、last_to_act=True
    obs0, _ = build_flop_observation(gs, actor=0, acts=acts)
    assert obs0.ip is True
    assert getattr(obs0, "first_to_act", False) is False
    assert getattr(obs0, "last_to_act", False) is True


def test_preflop_action_order_flags(monkeypatch, fake_annotation):
    from poker_core.suggest.observations import build_preflop_observation

    bb = 50
    p0 = _Player(stack=9000, invested_street=bb // 2, hole=["Ah", "Kh"])  # SB
    p1 = _Player(stack=9000, invested_street=bb)  # BB
    gs = _GS(street="preflop", button=0, to_act=0, bb=bb, pot=150, players=(p0, p1))

    acts = [
        LegalAction(action="check"),
        LegalAction(action="call", to_call=bb // 2),
        LegalAction(action="raise", min=bb * 3, max=bb * 9),
    ]

    # SB（actor=0）preflop 先行动：不使用 IP 概念；first_to_act=True、last_to_act=False
    obs_sb, _ = build_preflop_observation(gs, actor=0, acts=acts)
    assert obs_sb.ip is False
    assert getattr(obs_sb, "first_to_act", False) is True
    assert getattr(obs_sb, "last_to_act", False) is False

    # BB（actor=1）preflop 后行动：不使用 IP 概念；first_to_act=False、last_to_act=True
    obs_bb, _ = build_preflop_observation(gs, actor=1, acts=acts)
    assert obs_bb.ip is False
    assert getattr(obs_bb, "first_to_act", False) is False
    assert getattr(obs_bb, "last_to_act", False) is True


def test_last_aggressor_minimal(monkeypatch, fake_annotation):
    from poker_core.suggest.observations import build_flop_observation

    # 构造含 preflop raise 事件的简化状态，进入 flop 时 last_aggressor 应为该加注者
    p0 = _Player(stack=8000, invested_street=0, hole=["Ah", "Kh"])  # SB
    p1 = _Player(stack=8000, invested_street=0)  # BB

    class _GSWithEvents(_GS):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            # 事件序列：preflop 中 actor 0 raise，然后发翻牌
            self.events = [
                {"t": "raise", "who": 0, "to": 150},
                {"t": "board", "street": "flop"},
            ]

    gs = _GSWithEvents(
        street="flop",
        button=0,
        to_act=1,
        bb=50,
        pot=150,
        players=(p0, p1),
        board=["2d", "7c", "Jd"],
    )  # noqa: E501

    acts = [
        LegalAction(action="check"),
        LegalAction(action="call", to_call=50),
        LegalAction(action="raise", min=150, max=450),
    ]

    obs, _ = build_flop_observation(gs, actor=1, acts=acts)
    assert getattr(obs, "last_aggressor", None) == 0
