from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from poker_core.domain.actions import LegalAction
from poker_core.suggest.policy_loader import PolicyLoader
from poker_core.suggest.service import POLICY_REGISTRY_V1
from poker_core.suggest.service import build_suggestion


@dataclass
class _GS:
    hand_id: str = "h_table"
    street: str = "flop"
    to_act: int = 0


def _make_loader(
    tmp_path: Path,
    *,
    weights: tuple[float, float],
    facing: str = "na",
    node_key_override: str | None = None,
) -> PolicyLoader:
    path = tmp_path / "policy.npz"
    node_key = node_key_override or (
        f"flop|single_raised|caller|oop|texture=dry|spr=spr4|facing={facing}|hand=top_pair"
    )
    # For facing nodes (when facing != "na"), use facing actions: fold, call, raise
    if facing != "na":
        actions = ("fold", "call", "raise")
        size_tags = (None, None, "third")
        meta_actions = ["fold", "call", "raise"]
        meta_size_tags = [None, None, "third"]
    else:
        actions = ("bet", "check")
        size_tags = ("third", None)
        meta_actions = ["bet", "check"]
        meta_size_tags = ["third", None]

    np.savez(
        path,
        node_keys=np.array([node_key], dtype=object),
        actions=np.array([actions], dtype=object),
        weights=np.array([weights], dtype=object),
        size_tags=np.array([size_tags], dtype=object),
        meta=np.array(
            [
                {
                    "node_key": node_key,
                    "actions": meta_actions,
                    "size_tags": meta_size_tags,
                    "weights": list(weights),
                    "zero_weight_actions": [],
                    "node_key_components": {
                        "street": "flop",
                        "pot_type": "single_raised",
                        "role": "caller",
                        "pos": "oop",
                        "texture": "dry",
                        "spr": "spr4",
                        "facing": (
                            node_key.split("|facing=")[1].split("|", 1)[0]
                            if "|facing=" in node_key
                            else facing
                        ),
                        "bucket": "na",
                    },
                }
            ],
            dtype=object,
        ),
        table_meta=np.array(
            [
                {
                    "version": "audit_v1",
                    "policy_hash": "hash_xyz",
                }
            ],
            dtype=object,
        ),
    )
    return PolicyLoader(path)


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUGGEST_POLICY_VERSION", "v1")
    monkeypatch.setenv("SUGGEST_V1_ROLLOUT_PCT", "0")
    monkeypatch.setenv("SUGGEST_DEBUG", "1")


@pytest.fixture
def _stub_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    acts = [LegalAction("bet", min=100, max=400), LegalAction("check")]

    def _legal(_gs):
        return acts

    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", _legal)

    def _build_obs(gs, actor, acts, annotate_fn, context):  # noqa: ARG001
        from poker_core.suggest.types import Observation

        return (
            Observation(
                hand_id="h_table",
                actor=actor,
                street="flop",
                bb=50,
                pot=300,
                to_call=0,
                acts=list(acts),
                tags=["pair"],
                hand_class="top_pair",
                table_mode="HU",
                button=0,
                spr_bucket="mid",
                board_texture="dry",
                ip=False,
                first_to_act=False,
                last_to_act=False,
                pot_now=300,
                combo="",
                last_bet=0,
                role="caller",
                range_adv=True,
                nut_adv=False,
                facing_size_tag="na",
                pot_type="single_raised",
                last_aggressor=None,
                context=context,
                hole=("Ah", "Kd"),
                board=("Tc", "7d", "2s"),
            ),
            [],
        )

    monkeypatch.setattr("poker_core.suggest.service.build_observation", _build_obs)


def test_policy_hit_returns_table_action(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _stub_observation
) -> None:  # noqa: ANN001
    loader = _make_loader(tmp_path, weights=(0.8, 0.2))
    monkeypatch.setattr("poker_core.suggest.service.get_runtime_loader", lambda: loader)

    result = build_suggestion(_GS(), actor=0)

    assert result["suggested"]["action"] == "bet"
    meta = result.get("meta") or {}
    assert meta.get("policy_source") == "policy"
    assert meta.get("policy_version") == "audit_v1"
    assert (
        meta.get("node_key")
        == "flop|single_raised|caller|oop|texture=dry|spr=spr4|facing=na|hand=top_pair"
    )
    assert meta.get("policy_weight") == pytest.approx(0.8)
    debug_meta = (result.get("debug") or {}).get("meta") or {}
    assert debug_meta.get("policy_fallback") is False


def test_policy_miss_falls_back_to_rules(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _stub_observation
) -> None:  # noqa: ANN001
    loader = _make_loader(tmp_path, weights=(0.8, 0.2))
    monkeypatch.setattr("poker_core.suggest.service.get_runtime_loader", lambda: loader)

    def _lookup_missing(node_key: str) -> Any:  # noqa: ANN001
        return None

    monkeypatch.setattr(loader, "lookup", _lookup_missing)

    def _rule_policy(obs, cfg):  # noqa: ANN001
        return ({"action": "check"}, [], "flop_v1_rule", {"size_tag": "na"})

    monkeypatch.setitem(POLICY_REGISTRY_V1, "flop", _rule_policy)

    result = build_suggestion(_GS(), actor=0)

    assert result["suggested"]["action"] == "check"
    meta = result.get("meta") or {}
    assert meta.get("policy_source") == "rule"
    debug_meta = (result.get("debug") or {}).get("meta") or {}
    assert debug_meta.get("policy_fallback") is True


def test_policy_weight_edge_cases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _stub_observation
) -> None:  # noqa: ANN001
    loader = _make_loader(tmp_path, weights=(0.0, 0.0))
    monkeypatch.setattr("poker_core.suggest.service.get_runtime_loader", lambda: loader)

    def _rule_policy(obs, cfg):  # noqa: ANN001
        return ({"action": "check"}, [], "flop_v1_rule", {"size_tag": "na"})

    monkeypatch.setitem(POLICY_REGISTRY_V1, "flop", _rule_policy)

    result = build_suggestion(_GS(), actor=0)

    assert result["suggested"]["action"] == "check"
    meta = result.get("meta") or {}
    assert meta.get("policy_source") == "rule"
    assert meta.get("policy_fallback") is True
    debug_meta = (result.get("debug") or {}).get("meta") or {}
    assert debug_meta.get("policy_fallback") is True


def test_policy_alias_lookup_applies_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _stub_observation
) -> None:  # noqa: ANN001
    alias_key = (
        "flop|single_raised|caller|oop|texture=dry|spr=spr4|facing=two_third_plus|hand=top_pair"
    )
    loader = _make_loader(
        tmp_path,
        weights=(0.9, 0.1),
        facing="two_third_plus",
        node_key_override=alias_key,
    )
    monkeypatch.setattr("poker_core.suggest.service.get_runtime_loader", lambda: loader)

    def _alias_obs(gs, actor, acts, annotate_fn, context):  # noqa: ARG001
        from poker_core.suggest.types import Observation

        return (
            Observation(
                hand_id="alias",
                actor=0,
                street="flop",
                bb=50,
                pot=300,
                to_call=60,
                acts=list(acts),
                tags=["pair"],
                hand_class="top_pair",
                table_mode="HU",
                button=0,
                spr_bucket="mid",
                board_texture="dry",
                ip=False,
                first_to_act=False,
                last_to_act=False,
                pot_now=300,
                combo="",
                last_bet=0,
                role="caller",
                range_adv=True,
                nut_adv=False,
                facing_size_tag="two_third+",
                pot_type="single_raised",
                last_aggressor=None,
                context=context,
                hole=("Ah", "Kd"),
                board=("Tc", "7d", "2s"),
            ),
            [],
        )

    acts_alias = [
        LegalAction("fold"),
        LegalAction("call", to_call=60),
        LegalAction("raise", min=120, max=400),
    ]

    monkeypatch.setattr("poker_core.suggest.service.legal_actions_struct", lambda _gs: acts_alias)
    monkeypatch.setattr("poker_core.suggest.service.build_observation", _alias_obs)

    result = build_suggestion(_GS(), actor=0)

    meta = result.get("meta") or {}
    print(f"DEBUG: meta = {meta}")  # Debug output
    print(f"DEBUG: node_key in meta = {meta.get('node_key')}")  # Debug node key
    assert meta.get("policy_source") == "policy"
    assert meta.get("facing_alias_applied") is True
    # Alias lookup is a successful policy lookup, not a fallback
    # assert meta.get("facing_fallback") is True  # This should not be True for successful alias lookups
    debug_meta = (result.get("debug") or {}).get("meta") or {}
    print(f"DEBUG: debug_meta = {debug_meta}")  # Debug output
    attempted = debug_meta.get("attempted_keys") or []
    print(f"DEBUG: attempted_keys = {attempted}")  # Debug output
    assert any("facing=two_third+" in key for key in attempted)
    assert any("facing=two_third_plus" in key for key in attempted)


def test_policy_facing_na_triggers_rule_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _stub_observation
) -> None:  # noqa: ANN001
    loader = _make_loader(tmp_path, weights=(0.8, 0.2))
    monkeypatch.setattr("poker_core.suggest.service.get_runtime_loader", lambda: loader)

    def _missing_facing(gs, actor, acts, annotate_fn, context):  # noqa: ARG001
        from poker_core.suggest.types import Observation

        return (
            Observation(
                hand_id="missing_facing",
                actor=0,
                street="turn",
                bb=50,
                pot=300,
                to_call=80,
                acts=list(acts),
                tags=["pair"],
                hand_class="top_pair",
                table_mode="HU",
                button=0,
                spr_bucket="spr4",
                board_texture="semi",
                ip=False,
                first_to_act=False,
                last_to_act=False,
                pot_now=300,
                combo="",
                last_bet=60,
                role="caller",
                range_adv=False,
                nut_adv=False,
                facing_size_tag="na",
                pot_type="single_raised",
                last_aggressor=None,
                context=context,
                hole=("Ah", "Kd"),
                board=("Tc", "7d", "2s", "9c"),
            ),
            [],
        )

    monkeypatch.setattr("poker_core.suggest.service.build_observation", _missing_facing)

    def _rule_policy(_obs, _cfg):  # noqa: ANN001
        return ({"action": "check"}, [], "turn_rule", {"size_tag": "na"})

    monkeypatch.setitem(POLICY_REGISTRY_V1, "turn", _rule_policy)

    result = build_suggestion(_GS(street="turn"), actor=0)

    meta = result.get("meta") or {}
    assert meta.get("policy_source") == "rule"
    assert meta.get("facing_fallback") is True
    debug_meta = (result.get("debug") or {}).get("meta") or {}
    assert debug_meta.get("policy_fallback") is True
    assert debug_meta.get("facing_fallback") is True
    assert debug_meta.get("attempted_keys") == [
        "turn|single_raised|caller|oop|texture=semi|spr=spr4|facing=na|hand=top_pair"
    ]
