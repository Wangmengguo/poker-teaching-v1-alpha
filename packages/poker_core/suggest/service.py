# packages/poker_core/suggest/service.py
from __future__ import annotations

import logging
import math
import os
from collections.abc import Callable
from numbers import Real
from typing import Any

from poker_core.analysis import annotate_player_hand_from_gs
from poker_core.suggest.observations import build_observation

from ..domain.actions import LegalAction
from ..domain.actions import legal_actions_struct
from ..domain.actions import to_act_index
from .calculators import pot_odds as calc_pot_odds
from .codes import SCodes
from .codes import mk_rationale as R
from .context import SuggestContext
from .decision import Decision
from .explanations import render_explanations
from .fallback import choose_conservative_line
from .node_key import canonical_facing_tag
from .node_key import node_key_from_observation
from .policy import policy_flop_v1
from .policy import policy_postflop_v0_3
from .policy import policy_preflop_v0
from .policy import policy_preflop_v1
from .policy import policy_river_v1
from .policy import policy_turn_v1
from .policy_loader import PolicyEntry
from .policy_loader import get_runtime_loader
from .types import Observation
from .types import PolicyConfig
from .utils import drop_nones
from .utils import raise_to_amount
from .utils import size_to_amount
from .utils import stable_roll

try:  # Prometheus 指标可选
    from apps.web_django.api.metrics import inc_policy_fallback
    from apps.web_django.api.metrics import inc_policy_lookup
except Exception:  # pragma: no cover - metrics 模块缺失时降级为 no-op

    def inc_policy_lookup(
        result: str, street: str | None = None, facing: str | None = None
    ) -> None:
        return None

    def inc_policy_fallback(
        kind: str, street: str | None = None, facing: str | None = None
    ) -> None:
        return None


FACING_ALIAS_MAP = {
    "two_third+": ["two_third_plus"],
    "two_third_plus": ["two_third+"],
}


def _replace_facing(node_key: str, new_tag: str) -> str:
    parts = node_key.split("|")
    for idx, part in enumerate(parts):
        if part.startswith("facing="):
            updated = parts.copy()
            updated[idx] = f"facing={new_tag}"
            return "|".join(updated)
    # fallback：若键没有 facing 段，直接追加
    return "|".join([node_key, f"facing={new_tag}"])


def _extract_facing(node_key: str | None) -> str:
    if not node_key:
        return "na"
    for part in node_key.split("|"):
        if part.startswith("facing="):
            return part.split("=", 1)[1] or "na"
    return "na"


def _candidate_keys(base_key: str | None, facing_tag: str) -> list[tuple[str, str]]:
    if not base_key:
        return []
    seen: set[str] = set()
    candidates: list[tuple[str, str]] = []

    if base_key not in seen:
        candidates.append(("exact", base_key))
        seen.add(base_key)

    for alias_tag in FACING_ALIAS_MAP.get(facing_tag, []):
        alias_key = _replace_facing(base_key, alias_tag)
        if alias_key not in seen:
            candidates.append(("alias", alias_key))
            seen.add(alias_key)

    fallback_key = _replace_facing(base_key, "na")
    if fallback_key not in seen:
        candidates.append(("facing_na", fallback_key))

    return candidates


def _infer_amount_from_legal_actions(action: str | None, acts: list[LegalAction]) -> int | None:
    """Derive a legal amount for fallback suggestions lacking sizing."""

    if not action:
        return None

    spec = next((a for a in acts if a.action == action), None)
    if not spec:
        return None

    try:
        if action in {"bet", "raise", "allin"}:
            # Prefer the minimum legal amount so downstream clamps remain valid.
            if spec.min is not None:
                return int(spec.min)
            if spec.max is not None:
                return int(spec.max)
        elif action == "call" and spec.to_call is not None:
            return int(spec.to_call)
    except Exception:
        return None

    return None


def _build_observation(gs, actor: int, acts: list[LegalAction]):
    """向后兼容的别名，用于测试文件"""
    return build_observation(gs, actor, acts, annotate_fn=annotate_player_hand_from_gs)


def _clamp_amount_if_needed(
    suggested: dict[str, Any], acts: list[LegalAction]
) -> tuple[dict[str, Any], bool, dict[str, int | None]]:
    """将建议金额钳制到合法区间，并返回是否发生钳制及边界信息。"""
    name = suggested.get("action")
    if name not in {"bet", "raise", "allin"}:
        return (
            suggested,
            False,
            {"min": None, "max": None, "given": None, "chosen": None},
        )
    amt = suggested.get("amount")
    if amt is None:
        return (
            suggested,
            False,
            {"min": None, "max": None, "given": None, "chosen": None},
        )
    spec = next((a for a in acts if a.action == name), None)
    if not spec:
        return (
            suggested,
            False,
            {"min": None, "max": None, "given": int(amt), "chosen": int(amt)},
        )
    lo = spec.min if spec.min is not None else int(amt)
    hi = spec.max if spec.max is not None else int(amt)
    if lo is None or hi is None:
        return (
            suggested,
            False,
            {"min": None, "max": None, "given": int(amt), "chosen": int(amt)},
        )
    # 处理异常窗口：min > max（例如上游引擎的边界不一致）。
    # 为了确保打出服务层钳制信号，这里强制将金额压到 hi，并视为 clamped。
    if int(lo) > int(hi):
        clamped_val = int(hi)
        s2 = dict(suggested)
        s2["amount"] = clamped_val
        return (
            s2,
            True,
            {
                "min": int(lo),
                "max": int(hi),
                "given": int(amt),
                "chosen": int(clamped_val),
            },
        )
    clamped_val = max(int(lo), min(int(amt), int(hi)))
    if clamped_val != amt:
        s2 = dict(suggested)
        s2["amount"] = clamped_val
        return (
            s2,
            True,
            {
                "min": int(lo),
                "max": int(hi),
                "given": int(amt),
                "chosen": int(clamped_val),
            },
        )
    return (
        suggested,
        False,
        {"min": int(lo), "max": int(hi), "given": int(amt), "chosen": int(amt)},
    )


def _parse_frequency_value(freq: Any) -> float | None:
    if freq is None:
        return None

    value: float | None = None

    try:
        if isinstance(freq, str):
            text = freq.strip()
            if not text:
                return None
            if "/" in text and "%" not in text:
                num, _, denom = text.partition("/")
                value = float(num) / float(denom) if denom else None
            else:
                cleaned = text.replace("%", "")
                value = float(cleaned)
                if "%" in text or value > 1.0:
                    value /= 100.0
        elif isinstance(freq, Real) or hasattr(freq, "__float__"):
            value = float(freq)
        else:
            return None
    except Exception:
        return None

    if value is None or not math.isfinite(value):
        return None

    if value < 0:
        value = 0.0
    if value > 1:
        value = 1.0
    return value


def _frequency_label(value: float) -> str:
    pct = int(round(value * 100.0))
    pct = max(0, min(100, pct))
    if pct >= 95:
        return "几乎总是"
    if pct >= 70:
        return "大多数时候"
    if pct >= 45:
        return "约一半时间"
    if pct >= 20:
        return "偶尔出现"
    if pct >= 5:
        return "偶发出现"
    if value > 0:
        return "极少出现"
    return "几乎不出现"


def _frequency_pct_text(value: float) -> str:
    pct = int(round(value * 100.0))
    pct = max(0, min(100, pct))
    if 0 < value and pct == 0:
        return "<1%"
    return f"{pct}%"


_POLICY_WEIGHT_EPS = 1e-6


def _build_table_policy(
    entry: PolicyEntry, acts: list[LegalAction], original_policy_name: str | None = None
):
    if sum(entry.raw_weights) <= _POLICY_WEIGHT_EPS:
        print(f"DEBUG: _build_table_policy returning None due to zero weights: {entry.raw_weights}")
        return None
    legal_actions = {a.action for a in acts}
    ranked: list[tuple[int, str, float]] = []
    for idx, (action, weight) in enumerate(zip(entry.actions, entry.weights, strict=False)):
        if action in legal_actions:
            ranked.append((idx, action, float(weight)))
    if not ranked:
        print(
            f"DEBUG: _build_table_policy returning None due to no ranked actions. legal_actions={legal_actions}, entry.actions={entry.actions}"
        )
        return None
    ranked.sort(key=lambda item: item[2], reverse=True)
    top_idx, chosen_action, top_weight = ranked[0]
    if top_weight <= _POLICY_WEIGHT_EPS:
        print(f"DEBUG: _build_table_policy returning None due to low top_weight: {top_weight}")
        return None

    size_tag: str | None = None
    if top_idx < len(entry.size_tags):
        size_tag = entry.size_tags[top_idx]
    if not size_tag:
        meta_fallback = entry.meta or {}
        if isinstance(meta_fallback, dict):
            fallback_tag = meta_fallback.get("size_tag")
            if fallback_tag is not None:
                text = str(fallback_tag).strip()
                if text:
                    size_tag = text

    suggested: dict[str, Any] = {"action": chosen_action}
    if size_tag:
        suggested["size_tag"] = size_tag

    table_meta = dict(entry.table_meta)
    version = str(table_meta.get("version") or table_meta.get("policy_version") or "runtime")
    meta = dict(entry.meta or {})
    meta.update(
        {
            "policy_source": "policy",
            "policy_version": version,
            "policy_hash": table_meta.get("policy_hash"),
            "policy_weight": float(top_weight),
            "policy_distribution": entry.distribution(),
            "node_key": entry.node_key,
            "policy_table_meta": table_meta,
            "policy_fallback": False,
        }
    )
    if size_tag:
        meta.setdefault("size_tag", size_tag)

    # 优先使用原始策略名称，如果不存在则使用策略表定义的名称
    policy_name = original_policy_name or str(table_meta.get("policy_name") or f"{version}_table")
    meta.setdefault("policy_name", policy_name)
    rationale: list[dict[str, Any]] = []
    return suggested, rationale, policy_name, meta


def _frequency_context(freq: Any) -> dict[str, Any] | None:
    value = _parse_frequency_value(freq)
    if value is None:
        return None
    pct_text = _frequency_pct_text(value)
    label = _frequency_label(value)
    phrase = f"混合策略抽样（~{pct_text}）"
    return {
        "frequency_value": value,
        "frequency_pct_text": pct_text,
        "frequency_label": label,
        "frequency_phrase": phrase,
    }


def _describe_frequency(freq: Any) -> str | None:
    ctx = _frequency_context(freq)
    if not ctx:
        return None
    return ctx["frequency_phrase"]


_RIVER_TIER_LABELS = {
    "strong_value": "强成手",
    "medium_value": "中等成手",
    "weak_showdown": "弱摊牌",
    "air": "空气牌",
}

_RIVER_TIER_PLAN_DEFAULTS = {
    "strong_value": "薄价值下注或设置诱导线",
    "medium_value": "控制底池，保留摊牌",
    "weak_showdown": "优先免费摊牌，面对压力可弃牌",
    "air": "可用小注阻塞或直接放弃",
}

_RIVER_BLOCKER_LABELS = {
    "nut_flush_blocker": "坚果同花阻断",
    "straight_blocker": "关键顺子阻断",
    "full_house_blocker": "满堂红阻断",
}

_RIVER_BLOCKER_ACTIONS = {
    "nut_flush_blocker": "转为过牌诱导，避免阻断价值",
    "straight_blocker": "过牌控制下注节奏",
    "full_house_blocker": "控制底池，警惕被反超",
}

_RIVER_FACING_SIZE_TEXT = {
    "third": "小注（约 1/3 彩池）",
    "half": "中注（约 1/2 彩池）",
    "two_third+": "大注（≥ 2/3 彩池）",
    "pot": "满池下注",
    "all_in": "全下",
}

_ACTION_DECISION_TEXT = {
    "bet": "主动下注争取价值",
    "raise": "加注施压",
    "call": "跟注防守",
    "check": "过牌控制",
    "fold": "弃牌保守",
    "allin": "全下对抗",
}


def _action_decision_text(suggested: dict[str, Any] | None) -> str:
    action = str((suggested or {}).get("action") or "").lower()
    return _ACTION_DECISION_TEXT.get(action, "沿用当前策略")


def _river_explanation_items(
    street: str, meta: dict[str, Any], suggested: dict[str, Any] | None
) -> list[dict[str, Any]]:
    if str(street or "").lower() != "river":
        return []

    items: list[dict[str, Any]] = []
    tier_key = str((meta or {}).get("river_value_tier") or "")
    tier_label = _RIVER_TIER_LABELS.get(tier_key, tier_key or "")
    plan_text = str((meta or {}).get("plan") or "").strip()
    if not plan_text:
        plan_text = _RIVER_TIER_PLAN_DEFAULTS.get(tier_key, "")

    if tier_label and plan_text:
        items.append(
            R(
                SCodes.RIVER_VALUE_TIER_SUMMARY,
                data={
                    "river_value_tier_label": tier_label,
                    "river_plan_text": plan_text,
                },
            )
        )

    blockers = list((meta or {}).get("river_blockers") or [])
    if blockers:
        blk_key = str(blockers[0])
        blocker_label = _RIVER_BLOCKER_LABELS.get(blk_key, blk_key)
        adjust_text = _RIVER_BLOCKER_ACTIONS.get(blk_key)
        if not adjust_text:
            adjust_text = plan_text or _action_decision_text(suggested)
        items.append(
            R(
                SCodes.RIVER_BLOCKER_ADJUST,
                data={
                    "river_blocker_label": blocker_label,
                    "river_blocker_action": adjust_text,
                },
            )
        )

    facing_tag = str((meta or {}).get("facing_size_tag") or "").strip().lower()
    if facing_tag and facing_tag != "na":
        facing_text = _RIVER_FACING_SIZE_TEXT.get(facing_tag, facing_tag)
        decision_text = _action_decision_text(suggested)
        label = tier_label or _RIVER_TIER_LABELS.get(tier_key, tier_key)
        items.append(
            R(
                SCodes.RIVER_FACING_DECISION,
                data={
                    "facing_size_text": facing_text,
                    "river_value_tier_label": label or "河牌",
                    "river_facing_decision": decision_text,
                },
            )
        )

    return items


# 策略注册表（按版本/街选择）。PR-0：v1 映射到 v0 占位，保证行为不变。
PolicyFn = Callable[
    [Observation, PolicyConfig],
    tuple[dict[str, Any] | Decision, list[dict[str, Any]], str, dict[str, Any]],
]
POLICY_REGISTRY_V0: dict[str, PolicyFn] = {
    "preflop": policy_preflop_v0,  # type: ignore
    "flop": policy_postflop_v0_3,  # type: ignore
    "turn": policy_postflop_v0_3,  # type: ignore
    "river": policy_postflop_v0_3,  # type: ignore
}
POLICY_REGISTRY_V1: dict[str, PolicyFn] = {
    "preflop": policy_preflop_v1,
    "flop": policy_flop_v1,
    "turn": policy_turn_v1,
    "river": policy_river_v1,
}

# Backward-compat alias for tests/importers
POLICY_REGISTRY: dict[str, PolicyFn] = POLICY_REGISTRY_V0


def _policy_source_flag() -> str:
    raw = (os.getenv("SUGGEST_POLICY_SOURCE") or "rules").strip().lower()
    if raw == "lp_table":
        return "lp_table"
    return "rules"


def _choose_policy_version(hand_id: str) -> str:
    """返回 'v0' 或 'v1'（PR-0 中 v1 与 v0 行为一致，仅用于灰度管控与调试展示）。"""
    # Default to v1 so defense logic (preflop vs shove, flop/river fallbacks) is active by default
    mode = (os.getenv("SUGGEST_POLICY_VERSION") or "v1").strip().lower()
    if mode in {"v0", "v1", "v1_preflop"}:  # v1_preflop 在 PR-0 等同 v1
        return "v1" if mode != "v0" else "v0"
    if mode == "auto":
        pct = int(os.getenv("SUGGEST_V1_ROLLOUT_PCT") or 0)
        return "v1" if stable_roll(hand_id or "", pct) else "v0"
    return "v0"


def build_suggestion(gs, actor: int, cfg: PolicyConfig | None = None) -> dict[str, Any]:
    """Suggest 入口（纯函数策略版）。

    契约：
    - 若 actor != gs.to_act → PermissionError（视图层转 409）
    - 若无法产生合法建议 → ValueError（视图层转 422）
    - cfg 可选：缺省使用 PolicyConfig()
    """
    cur = to_act_index(gs)
    if cur != actor:
        raise PermissionError("actor is not to_act")

    # 只计算一次合法动作
    acts = legal_actions_struct(gs)
    if not acts:
        raise ValueError("No legal actions")

    ctx = SuggestContext.build()

    # 组装 Observation
    obs, pre_rationale = build_observation(
        gs, actor, acts, annotate_fn=annotate_player_hand_from_gs, context=ctx
    )

    # 选择策略（按版本 + 街）
    version = _choose_policy_version(str(getattr(gs, "hand_id", "")))
    reg = POLICY_REGISTRY_V1 if version == "v1" else POLICY_REGISTRY_V0
    policy_fn = reg.get(obs.street) or (
        policy_preflop_v0 if obs.street == "preflop" else policy_postflop_v0_3
    )

    # 计算原始策略名称
    raw_policy_name = getattr(policy_fn, "__name__", "unknown")
    if raw_policy_name.startswith("policy_"):
        original_policy_name = raw_policy_name[len("policy_") :]
    else:
        original_policy_name = raw_policy_name

    table_override: tuple[dict[str, Any], list[dict[str, Any]], str, dict[str, Any]] | None = None
    runtime_meta_hint: dict[str, Any] = {}
    debug_policy_fallback: bool | None = None

    facing_tag = canonical_facing_tag(getattr(obs, "facing_size_tag", None))
    facing_context = getattr(obs, "street", "").lower() in {"flop", "turn", "river"}
    facing_context = facing_context and int(getattr(obs, "to_call", 0) or 0) > 0
    facing_fallback_required = facing_context and facing_tag == "na"

    loader = get_runtime_loader()
    node_key_runtime: str | None = None
    attempted_keys: list[str] = []
    alias_applied = False
    facing_fallback_hit = facing_fallback_required

    if facing_fallback_required:
        try:
            node_key_runtime = node_key_from_observation(obs)
        except Exception:
            node_key_runtime = None
        if node_key_runtime:
            attempted_keys.append(node_key_runtime)
        runtime_meta_hint = {
            "policy_source": "rule",
            "policy_fallback": True,
            "node_key": node_key_runtime,
            "facing_fallback": True,
        }
        debug_policy_fallback = True
        facing_fallback_hit = (
            True  # Ensure facing_fallback_hit is set when facing fallback is required
        )
        inc_policy_lookup("skip", obs.street, facing_tag)
        inc_policy_fallback("facing_na", obs.street, facing_tag)
        loader = None

    entry: PolicyEntry | None = None

    if loader is not None:
        try:
            node_key_runtime = node_key_from_observation(obs)
        except Exception:
            node_key_runtime = None

        candidates = _candidate_keys(node_key_runtime, facing_tag)
        for kind, candidate in candidates:
            attempted_keys.append(candidate)
            # Debug: log candidate lookup
            # print(f"DEBUG: Trying candidate: kind={kind}, candidate={candidate}")
            try:
                result = loader.lookup(candidate)
            except Exception:
                logging.getLogger(__name__).exception(
                    "policy_table_lookup_failed", extra={"node_key": candidate}
                )
                runtime_meta_hint = {
                    "policy_source": "rule",
                    "policy_fallback": True,
                    "node_key": candidate,
                    "facing_fallback": kind != "exact",
                }
                debug_policy_fallback = True
                inc_policy_lookup("error", obs.street, _extract_facing(candidate))
                inc_policy_fallback("rule", obs.street, facing_tag)
                break

            if result is None:
                inc_policy_lookup("miss", obs.street, _extract_facing(candidate))
                continue

            entry = result
            alias_applied = kind == "alias"
            # 只有当不是精确匹配且不是别名匹配时，才标记为 facing_fallback_hit
            # 别名匹配虽然不是精确匹配，但仍然是成功的策略表查找
            if kind not in ("exact", "alias"):
                facing_fallback_hit = True
            inc_policy_lookup("hit", obs.street, _extract_facing(candidate))
            try:
                table_override = _build_table_policy(entry, acts, original_policy_name)
            except Exception:
                logging.getLogger(__name__).exception(
                    "policy_table_build_failed", extra={"node_key": entry.node_key}
                )
                runtime_meta_hint = {
                    "policy_source": "rule",
                    "policy_fallback": True,
                    "node_key": entry.node_key,
                    "policy_version": entry.table_meta.get("version"),
                    "policy_hash": entry.table_meta.get("policy_hash"),
                    "facing_fallback": kind != "exact",
                }
                debug_policy_fallback = True
                inc_policy_fallback("rule", obs.street, facing_tag)
                entry = None
            else:
                if table_override is None:
                    runtime_meta_hint = {
                        "policy_source": "rule",
                        "policy_fallback": True,
                        "node_key": entry.node_key,
                        "policy_version": entry.table_meta.get("version"),
                        "policy_hash": entry.table_meta.get("policy_hash"),
                        "policy_distribution": entry.distribution(),
                        "facing_fallback": kind != "exact",
                    }
                    debug_policy_fallback = True
                    inc_policy_fallback("rule", obs.street, facing_tag)
                    entry = None
                    print(f"DEBUG: Set runtime_meta_hint for table_override=None, kind={kind}")
                else:
                    debug_policy_fallback = False
                    runtime_meta_hint = {}
                    # Debug: log that we cleared runtime_meta_hint for successful policy lookup
                    print(
                        f"DEBUG: Cleared runtime_meta_hint for successful policy lookup, kind={kind}, table_override={table_override is not None}"
                    )
            if entry is not None or debug_policy_fallback:
                break

        if entry is None and not runtime_meta_hint:
            # Debug: log when we set runtime_meta_hint for rule fallback
            print(
                f"DEBUG: Setting runtime_meta_hint for rule fallback: entry={entry}, runtime_meta_hint={runtime_meta_hint}"
            )
            runtime_meta_hint = {
                "policy_source": "rule",
                "policy_fallback": True,
                "node_key": node_key_runtime,
                "facing_fallback": True,
            }
            debug_policy_fallback = True
            inc_policy_lookup("miss", obs.street, facing_tag)
            inc_policy_fallback("rule", obs.street, facing_tag)

    # 执行策略
    cfg = cfg or PolicyConfig()
    suggested: dict[str, Any] = {}
    rationale: list[dict[str, Any]] = []
    meta_from_policy: dict[str, Any] = {}
    decision_obj: Decision | None = None
    raw_policy_name = getattr(policy_fn, "__name__", "unknown")
    if raw_policy_name.startswith("policy_"):
        policy_name = raw_policy_name[len("policy_") :]
    else:
        policy_name = raw_policy_name
    fallback_used = False
    fallback_meta: dict[str, Any] = {}
    fallback_rationale: list[dict[str, Any]] = []

    def _engage_fallback(reason: str | None = None) -> None:
        nonlocal suggested, fallback_used, fallback_meta, fallback_rationale, meta_from_policy
        fb_suggested, fb_meta, fb_rationale = choose_conservative_line(obs, acts)
        fallback_used = True
        suggested = fb_suggested
        fallback_meta = dict(fb_meta or {})
        fallback_rationale = list(fb_rationale or [])
        if reason:
            fallback_meta.setdefault("fallback_reason", reason)
        meta_from_policy = dict(fallback_meta)
        inc_policy_fallback("conservative", obs.street, facing_tag)

    if table_override is not None:
        suggested, rationale, policy_name, meta_from_policy = table_override
        if alias_applied:
            meta_from_policy = dict(meta_from_policy or {})
            meta_from_policy["facing_alias_applied"] = True
        # 别名匹配虽然成功，但仍然不是精确匹配，应该标记为 facing_fallback
        # 但不应该因此而回退到规则策略，除非真的查找失败
        if facing_fallback_hit or alias_applied:
            meta_from_policy = dict(meta_from_policy or {})
            meta_from_policy.setdefault("facing_fallback", True)
    else:
        try:
            out = policy_fn(obs, cfg)
        except Exception:
            logging.getLogger(__name__).exception(
                "policy %s failed; using conservative fallback",
                getattr(policy_fn, "__name__", "unknown"),
            )
            _engage_fallback("policy_exception")
            out = None
        else:
            if isinstance(out, Decision):
                decision_obj = out
                rationale = []
                policy_name = "unknown"
            elif isinstance(out, tuple):
                if out and isinstance(out[0], Decision):
                    decision_obj = out[0]
                    rationale = list(out[1]) if len(out) > 1 else []  # type: ignore
                    policy_name = str(out[2]) if len(out) > 2 else "unknown"
                    meta_from_policy = dict(out[3]) if len(out) > 3 else {}
                elif len(out) == 4:
                    suggested, rationale, policy_name, meta_from_policy = out  # type: ignore
                else:
                    suggested, rationale, policy_name = out  # type: ignore
                    meta_from_policy = {}
            else:
                raise ValueError("Policy returned unsupported response type")

    if decision_obj is not None:
        suggested, decision_meta, decision_rationale = decision_obj.resolve(obs, acts, cfg)
        meta_from_policy = {**(decision_meta or {}), **(meta_from_policy or {})}
        rationale = list(rationale or []) + list(decision_rationale or [])
    elif not fallback_used:
        suggested = suggested  # type: ignore  # already set in non-decision branches

    if not fallback_used and not suggested:
        _engage_fallback("empty_suggestion")
    # 若策略仅返回 size_tag（无金额），在服务层统一换算
    try:
        if (
            suggested
            and suggested.get("action") in {"bet", "raise"}
            and (suggested.get("amount") is None)
        ):
            size_tag = (meta_from_policy or {}).get("size_tag")
            if size_tag:
                if suggested.get("action") == "raise":
                    # use raise-to semantics for postflop
                    try:
                        modes = ctx.modes
                        cap_ratio = (
                            (modes.get("HU", {}) or {}).get("postflop_cap_ratio", 0.85)
                            if isinstance(modes, dict)
                            else 0.85
                        )
                    except Exception:
                        cap_ratio = 0.85
                    eff_stack = 0  # conservative; service-level clamp will still enforce bounds
                    amt = raise_to_amount(
                        pot_now=int(getattr(obs, "pot_now", obs.pot) or 0),
                        last_bet=int(getattr(gs, "last_bet", 0) or 0),
                        size_tag=str(size_tag),
                        bb=int(obs.bb or 1),
                        eff_stack=eff_stack,
                        cap_ratio=float(cap_ratio),
                    )
                else:
                    amt = size_to_amount(
                        pot=int(getattr(obs, "pot_now", obs.pot) or 0),
                        last_bet=int(getattr(gs, "last_bet", 0) or 0),
                        size_tag=str(size_tag),
                        bb=int(obs.bb or 1),
                    )
                if amt is not None:
                    suggested["amount"] = int(amt)
        if suggested and suggested.get("amount") is None:
            inferred_amt = _infer_amount_from_legal_actions(suggested.get("action"), acts)
            if inferred_amt is not None:
                suggested["amount"] = inferred_amt
        # Min-reopen lift for postflop raise sizing (to-amount semantics)
        if suggested and suggested.get("action") == "raise" and suggested.get("amount") is not None:
            try:
                raise_spec = next((a for a in acts if a.action == "raise"), None)
                if (
                    raise_spec
                    and raise_spec.min is not None
                    and int(suggested["amount"]) < int(raise_spec.min)
                ):
                    # Lift to legal minimum re-open amount.
                    suggested["amount"] = int(raise_spec.min)
                    # For legacy (non-Decision) policies, emit rationale to explain the lift
                    # so UI/users know why the raise amount changed. Decision.resolve already
                    # appends this code on its own; gate by decision_obj is None to avoid dupes.
                    if decision_obj is None:
                        rationale = list(rationale or [])
                        rationale.append(R(SCodes.FL_MIN_REOPEN_ADJUSTED))
            except Exception:
                pass
    except Exception:
        pass

    # 注入预先的告警（例如分析缺失）
    if pre_rationale:
        rationale = list(pre_rationale) + list(rationale or [])
    # 已由 Decision.resolve 追加 PL_MIN_REOPEN_LIFT；无需重复

    # 名称校验
    names = {a.action for a in acts}
    if suggested.get("action") not in names:
        _engage_fallback("illegal_action")
        if suggested.get("action") not in names:
            raise ValueError("Policy produced illegal action")

    if runtime_meta_hint:
        meta_from_policy = {**(meta_from_policy or {}), **runtime_meta_hint}

    if fallback_meta:
        meta_from_policy = {**(meta_from_policy or {}), **fallback_meta}

    if fallback_rationale:
        rationale = list(rationale or []) + list(fallback_rationale)

    # SB 补盲（limp）时确保附带解释码（防止上游遗漏）
    try:
        if (
            obs.street == "preflop"
            and suggested.get("action") == "call"
            and not bool(obs.ip)  # SB preflop 为 OOP
            and int(obs.to_call or 0) <= int(obs.bb or 0)
        ):
            rationale = list(rationale or [])
            codes = {str((r or {}).get("code")) for r in rationale}
            if "PF_LIMP_COMPLETE_BLIND" not in codes:
                rationale.append(R(SCodes.PF_LIMP_COMPLETE_BLIND))
    except Exception:
        pass

    # 越界金额钳制 + 告警
    suggested2, clamped, clamp_info = _clamp_amount_if_needed(suggested, acts)
    if clamped:
        rationale.append(R(SCodes.WARN_CLAMPED, data=clamp_info))

    # 兼容 + 扩展返回
    resp: dict[str, Any] = {
        "hand_id": getattr(gs, "hand_id", None),
        "actor": actor,
        "suggested": suggested2,
        "rationale": rationale,
        "policy": policy_name,
        "confidence": 0.5,
    }

    # meta 仅在有值时返回；由策略层提供
    meta_dict = dict(meta_from_policy or {})
    meta_dict.setdefault("policy_source", _policy_source_flag())
    meta_dict.setdefault("baseline", "GTO")
    meta_dict.setdefault("mode", "GTO")
    meta_dict.setdefault("facing_size_tag", facing_tag)
    if facing_fallback_hit:
        meta_dict["facing_fallback"] = True
    elif "facing_fallback" in meta_dict and not meta_dict["facing_fallback"]:
        meta_dict.pop("facing_fallback", None)
    if alias_applied:
        meta_dict["facing_alias_applied"] = True
    street = str(getattr(obs, "street", "") or "").strip().lower()
    size_val = meta_dict.get("size_tag")
    if isinstance(size_val, str):
        size_val = size_val.strip()

    if street == "preflop":
        # Preflop 策略不应返回 size_tag；若策略层未设置则从 meta 中移除，保持兼容旧快照。
        if not size_val:
            meta_dict.pop("size_tag", None)
    else:
        # Postflop：确保 meta.size_tag 始终为非空字符串
        if not size_val:
            suggested_size_tag = None
            if suggested and suggested.get("action") in {"bet", "raise"}:
                if isinstance(suggested.get("size_tag"), str):
                    suggested_size_tag = str(suggested["size_tag"]).strip()
            # 默认占位符：当策略未提供或选择了非下注动作时，使用 "na"
            size_val = suggested_size_tag or "na"
        meta_dict["size_tag"] = str(size_val)
    if "node_key" not in meta_dict:
        try:
            meta_dict["node_key"] = node_key_from_observation(obs)
        except Exception:
            meta_dict["node_key"] = None
    if fallback_used:
        meta_dict["policy_source"] = "fallback"
        meta_dict["fallback_used"] = True
    meta_clean = drop_nones(meta_dict)
    if meta_clean:
        resp["meta"] = meta_clean

    # Compute confidence after clamp, based on rationale codes + meta hints (small tweaks)
    try:
        codes = {str((r or {}).get("code")) for r in (rationale or [])}
        hit_range = any(
            c in {"PF_OPEN_RANGE_HIT", "PF_DEFEND_3BET", "PF_DEFEND_PRICE_OK"} for c in codes
        )
        price_or_size_ok = any(
            c in {"PF_DEFEND_PRICE_OK", "PF_OPEN_RANGE_HIT", "PF_DEFEND_3BET"} for c in codes
        )
        fallback = any(
            c in {"CFG_FALLBACK_USED", "PF_NO_LEGAL_RAISE", "PF_LIMP_COMPLETE_BLIND"} for c in codes
        )
        meta_all = resp.get("meta") or {}
        size_meta = meta_all.get("size_tag")
        size_is_mainline = (
            isinstance(size_meta, str)
            and size_meta.strip()
            and size_meta.strip().lower() not in {"na", "n/a"}
        )
        hit_mainline = (
            str(resp.get("policy")) == "flop_v1"
            and size_is_mainline
            and int(getattr(obs, "to_call", 0) or 0) == 0
        )
        has_plan = (
            isinstance(meta_all.get("plan"), str) and len(str(meta_all.get("plan") or "")) > 0
        )
        base = 0.5
        base += 0.3 if hit_range else 0.0
        base += 0.2 if price_or_size_ok else 0.0
        base += 0.05 if hit_mainline else 0.0
        base += 0.05 if has_plan else 0.0
        base -= 0.1 if clamped else 0.0
        base -= 0.1 if fallback else 0.0
        resp["confidence"] = max(0.5, min(0.9, base))
    except Exception:
        pass

    if (os.getenv("SUGGEST_DEBUG") or "0") == "1":
        cfg_versions = {
            "open": int(ctx.versions.get("open", 0)),
            "vs": int(ctx.versions.get("vs", 0)),
            "modes": int(ctx.versions.get("modes", 0)),
        }
        profile = ctx.profile.config_profile
        # debug units/deriveds for preflop v1 troubleshooting
        try:
            to_call_bb_dbg = float(obs.to_call) / float(obs.bb) if obs.bb else 0.0
            open_to_bb_dbg = (
                to_call_bb_dbg + 1.0 if obs.to_call and obs.street == "preflop" else None
            )
            pot_odds_dbg = calc_pot_odds(obs.to_call, obs.pot_now)
            r2bb_dbg = None
            r2amt_dbg = None
            if resp.get("policy") == "preflop_v1":
                r2bb_dbg = (resp.get("meta") or {}).get("reraise_to_bb")
                if (resp.get("suggested") or {}).get("action") == "raise":
                    r2amt_dbg = (resp.get("suggested") or {}).get("amount")
        except Exception:
            to_call_bb_dbg = None
            open_to_bb_dbg = None
            pot_odds_dbg = None
            r2bb_dbg = None
            r2amt_dbg = None
        debug_meta = {
            "policy_version": version,
            "table_mode": obs.table_mode,
            "spr_bucket": obs.spr_bucket,
            "board_texture": obs.board_texture,
            "pot_type": getattr(obs, "pot_type", "single_raised"),
            "rollout_pct": int(os.getenv("SUGGEST_V1_ROLLOUT_PCT") or 0),
            "rolled_to_v1": (version == "v1"),
            "config_versions": cfg_versions,
            "config_profile": profile,
            "strategy": ctx.profile.strategy_name,
            # units
            "to_call_bb": to_call_bb_dbg,
            "open_to_bb": open_to_bb_dbg,
            "pot_odds": None if pot_odds_dbg is None else round(pot_odds_dbg, 6),
            "reraise_to_bb": r2bb_dbg,
            "reraise_to_amount": r2amt_dbg,
            "fourbet_to_bb": (resp.get("meta") or {}).get("fourbet_to_bb"),
            "cap_bb": (resp.get("meta") or {}).get("cap_bb"),
            "bucket": (resp.get("meta") or {}).get("bucket"),
            # flop v1 diagnostics
            "role": getattr(obs, "role", "na"),
            "range_adv": getattr(obs, "range_adv", False),
            "nut_adv": getattr(obs, "nut_adv", False),
            "facing_size_tag": facing_tag,
            "rule_path": (resp.get("meta") or {}).get("rule_path"),
        }
        mix_debug = (resp.get("meta") or {}).get("mix")
        if mix_debug:
            debug_meta["mix"] = mix_debug
        node_key = (resp.get("meta") or {}).get("node_key")
        if node_key is not None:
            debug_meta["node_key"] = node_key
        if (resp.get("meta") or {}).get("facing_fallback"):
            debug_meta["facing_fallback"] = True
        if attempted_keys:
            debug_meta["attempted_keys"] = attempted_keys
        if alias_applied:
            debug_meta["facing_alias_applied"] = True
        resp["debug"] = {"meta": debug_meta}

    # Structured log for v1 (or when debug enabled), including profile
    try:
        log = logging.getLogger(__name__)
        if version == "v1" or (os.getenv("SUGGEST_DEBUG") or "0") == "1":
            action = str(resp.get("suggested", {}).get("action", ""))
            amount = resp.get("suggested", {}).get("amount")
            meta_ref = resp.get("meta") or {}
            mix_info = meta_ref.get("mix") if isinstance(meta_ref, dict) else None
            mix_applied = bool(mix_info)
            fallback_flag = bool(meta_ref.get("fallback_used") or fallback_used)
            mix_index = None
            if isinstance(mix_info, dict):
                mix_index = mix_info.get("chosen_index")
            log.info(
                "suggest_v1",
                extra={
                    "policy_name": policy_name,
                    "street": obs.street,
                    "action": action,
                    "amount": amount,
                    "size_tag": (resp.get("meta") or {}).get("size_tag"),
                    "plan": (resp.get("meta") or {}).get("plan"),
                    "hand_class6": getattr(obs, "hand_class", None),
                    "config_profile": resp.get("debug", {}).get("meta", {}).get("config_profile"),
                    "strategy": ctx.profile.strategy_name,
                    "rolled_to_v1": (version == "v1"),
                    "confidence": resp.get("confidence"),
                    "pot_type": getattr(obs, "pot_type", None),
                    "to_call_bb": (float(obs.to_call) / float(obs.bb) if obs.bb else None),
                    "pot_odds": calc_pot_odds(obs.to_call, obs.pot_now),
                    "threebet_to_bb": (resp.get("meta") or {}).get("reraise_to_bb"),
                    "fourbet_to_bb": (resp.get("meta") or {}).get("fourbet_to_bb"),
                    "bucket": (resp.get("meta") or {}).get("bucket"),
                    "rule_path": (resp.get("meta") or {}).get("rule_path"),
                    "node_key": (resp.get("meta") or {}).get("node_key"),
                    "policy_source": (resp.get("meta") or {}).get("policy_source"),
                    "mix_applied": mix_applied,
                    "mix.chosen_index": mix_index,
                    "fallback_used": fallback_flag,
                    "frequency": (resp.get("meta") or {}).get("frequency"),
                },
            )
    except Exception:
        pass

    debug_meta_flag = debug_policy_fallback
    if meta_clean:
        if "policy_fallback" in meta_clean:
            debug_meta_flag = bool(meta_clean.get("policy_fallback"))
    if debug_meta_flag is not None:
        dbg = resp.setdefault("debug", {})
        dbg_meta = dbg.setdefault("meta", {})
        dbg_meta["policy_fallback"] = bool(debug_meta_flag)
        # Also set facing_fallback if present in meta
        if meta_clean and "facing_fallback" in meta_clean:
            dbg_meta["facing_fallback"] = bool(meta_clean.get("facing_fallback"))

    # Optional: render natural-language explanations for teaching UI
    try:
        extras = {
            "action": (resp.get("suggested") or {}).get("action"),
            "amount": (resp.get("suggested") or {}).get("amount"),
        }
        meta_ref = resp.get("meta")
        if not isinstance(meta_ref, dict):
            meta_ref = {}
            resp["meta"] = meta_ref
        augmented = list(rationale or [])

        freq_ctx = _frequency_context(meta_ref.get("frequency"))
        if freq_ctx:
            meta_ref["frequency_value"] = freq_ctx["frequency_value"]
            meta_ref["frequency_pct_text"] = freq_ctx["frequency_pct_text"]
            meta_ref["frequency_phrase"] = freq_ctx["frequency_phrase"]
            if freq_ctx.get("frequency_label"):
                meta_ref["frequency_label"] = freq_ctx["frequency_label"]
            freq_data: dict[str, Any] = {
                "frequency_pct": freq_ctx["frequency_pct_text"],
            }
            if freq_ctx.get("frequency_label"):
                freq_data["frequency_label"] = freq_ctx["frequency_label"]
            augmented.append(R(SCodes.MIX_FREQUENCY_HINT, data=freq_data))

        augmented.extend(
            _river_explanation_items(getattr(obs, "street", ""), meta_ref, resp.get("suggested"))
        )

        exp_list = list(render_explanations(rationale=augmented, meta=meta_ref, extras=extras))
        if exp_list:
            resp["explanations"] = exp_list
    except Exception:
        pass

    return drop_nones(resp)
