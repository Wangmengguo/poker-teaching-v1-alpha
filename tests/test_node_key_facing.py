from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from poker_core.domain.actions import LegalAction
from poker_core.suggest.node_key import node_key_from_observation
from poker_core.suggest.service import POLICY_REGISTRY_V1
from poker_core.suggest.service import build_suggestion
from poker_core.suggest.types import Observation

from tools.build_policy_solution import build_solution_from_configs

REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_obs(**overrides) -> Observation:
    base = dict(
        hand_id="nk_turn",
        actor=0,
        street="turn",
        bb=50,
        pot=300,
        to_call=60,
        acts=[
            LegalAction("fold"),
            LegalAction("call", to_call=60),
            LegalAction("raise", min=120, max=400),
        ],
        tags=[],
        hand_class="top_pair",
        table_mode="HU",
        spr_bucket="spr4",
        board_texture="semi",
        ip=False,
        first_to_act=False,
        last_to_act=False,
        pot_now=300,
        combo="",
        last_bet=60,
        hand_strength=None,
        role="caller",
        range_adv=False,
        nut_adv=False,
        facing_size_tag="half",
        pot_type="single_raised",
        last_aggressor=None,
        context=None,
        hole=(),
        board=(),
    )
    base.update(overrides)
    return Observation(**base)


def test_node_key_includes_facing_when_available() -> None:
    obs = _make_obs(street="river", facing_size_tag="third", to_call=30, pot_now=120)
    key = node_key_from_observation(obs)
    assert "|facing=third|" in key
    assert key.endswith("hand=top_pair")


def test_node_key_facing_na_when_no_bet() -> None:
    obs = _make_obs(to_call=0, facing_size_tag="na")
    key = node_key_from_observation(obs)
    assert "|facing=na|" in key


@dataclass
class _GS:
    hand_id: str = "nk"
    street: str = "turn"
    to_act: int = 0


def test_facing_fallback_to_default_size(monkeypatch: pytest.MonkeyPatch) -> None:
    obs = _make_obs(facing_size_tag="na", to_call=80, pot_now=160)

    def _legal_actions(_gs):
        return obs.acts

    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", _legal_actions)
    monkeypatch.setattr(
        "poker_core.suggest.service.build_observation",
        lambda *args, **kwargs: (obs, []),
    )

    # 模拟策略表查找失败，触发 facing_fallback
    def _lookup_missing(node_key: str):  # noqa: ANN001
        return None

    monkeypatch.setattr(
        "poker_core.suggest.service.get_runtime_loader",
        lambda: type("Loader", (), {"lookup": _lookup_missing})(),
    )

    def _rule_policy(_obs, _cfg):  # noqa: ANN001
        return ({"action": "call"}, [], "turn_rule", {"size_tag": "na"})

    monkeypatch.setitem(POLICY_REGISTRY_V1, "turn", _rule_policy)

    result = build_suggestion(_GS(), actor=0)

    meta = result.get("meta") or {}
    assert meta.get("policy_source") == "rule"
    assert meta.get("facing_fallback") is True

    debug_meta = (result.get("debug") or {}).get("meta") or {}
    assert debug_meta.get("policy_fallback") is True
    assert debug_meta.get("facing_fallback") is True


def test_facing_consistency_across_runtime_offline() -> None:
    solution = build_solution_from_configs(REPO_ROOT)
    node = next(
        item
        for item in solution["nodes"]
        if item.get("street") == "turn" and item.get("facing") == "half"
    )
    obs = _make_obs(
        street=node["street"],
        pot_type=node["pot_type"],
        role=node["role"],
        ip=(node["pos"] == "ip"),
        board_texture=node["texture"],
        spr_bucket=node["spr"],
        hand_class=node["hand"],
        facing_size_tag=node["facing"],
        pot=200,
        pot_now=200,
        to_call=100,
    )
    key_runtime = node_key_from_observation(obs)
    assert key_runtime == node["node_key"]

    arms = node.get("actions", [])
    if obs.facing_size_tag != "na":
        # Offline actions should include call/fold for facing nodes
        action_names = {arm.get("action") for arm in arms}
        assert {"call", "fold"}.issubset(action_names)
    else:
        assert any(arm.get("action") == "bet" for arm in arms)
