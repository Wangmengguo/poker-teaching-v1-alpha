"""
packages/poker_core/suggest/policy.py
preflop_v0, postflop_v0_3, preflop_v1
签名改造：只接收 Observation/PolicyConfig；不直接依赖 GameState/analysis/metrics。
返回值保持原契约： (suggested: dict, rationale: list[dict], policy_name: str)
"""

from __future__ import annotations

from typing import Any

from .codes import SCodes
from .codes import mk_rationale as R
from .decision import Decision, SizeSpec
from .flop_rules import get_flop_rules
from .policy_preflop import decide_bb_defend, decide_sb_open, decide_sb_vs_threebet
from .preflop_tables import bucket_facing_size
from .turn_river_rules import get_river_rules, get_turn_rules
from .types import Observation, PolicyConfig
from .utils import (
    HC_OP_TPTK,
    HC_STRONG_DRAW,
    HC_VALUE,
    find_action,
    pick_betlike_action,
    to_call_from_acts,
)

# 与 analysis 中口径保持一致的范围判定（避免耦合：基于 tags/hand_class）
OPEN_RANGE_TAGS = {"pair", "suited_broadway", "Ax_suited", "broadway_offsuit"}
CALL_RANGE_TAGS = {"pair", "suited_broadway", "Ax_suited", "broadway_offsuit"}


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(int(v), hi))


def _in_open_range(tags: list[str], hand_class: str) -> bool:
    s = set(tags or [])
    return bool(s & OPEN_RANGE_TAGS) or hand_class in (
        "Ax_suited",
        "suited_broadway",
        "broadway_offsuit",
        "pair",
    )


def _in_call_range(tags: list[str], hand_class: str) -> bool:
    s = set(tags or [])
    return bool(s & CALL_RANGE_TAGS) or hand_class in (
        "Ax_suited",
        "suited_broadway",
        "broadway_offsuit",
        "pair",
    )


def policy_preflop_v0(
    obs: Observation, cfg: PolicyConfig
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    """Preflop 策略 v0（纯函数）。

    规则：
    - 未面对下注：范围内以 open_size_bb*bb 开局（bet/raise），否则优先 check。
    - 面对下注：范围内且 to_call <= call_threshold_bb*bb → call，否则 fold。
    """
    acts = list(obs.acts or [])
    if not acts:
        raise ValueError("No legal actions")

    rationale: list[dict[str, Any]] = []
    bb = int(obs.bb)
    to_call = int(obs.to_call if obs.to_call is not None else to_call_from_acts(acts))

    # 1) 未面对下注
    if to_call == 0:
        if _in_open_range(obs.tags, obs.hand_class):
            betlike = pick_betlike_action(acts)
            if (
                betlike
                and betlike.min is not None
                and betlike.max is not None
                and betlike.min <= betlike.max
            ):
                target = int(round(cfg.open_size_bb * bb))
                amt = _clamp(target, betlike.min, betlike.max)
                code_def = SCodes.PF_OPEN_BET if betlike.action == "bet" else SCodes.PF_OPEN_RAISE
                rationale.append(
                    R(
                        code_def,
                        msg=f"未入池：{cfg.open_size_bb}bb 开局（{betlike.action}）。",
                        data={"bb": bb, "chosen": amt, "bb_mult": cfg.open_size_bb},
                    )
                )
                return (
                    {"action": betlike.action, "amount": amt},
                    rationale,
                    "preflop_v0",
                )
        # 不在范围：优先过牌
        if find_action(acts, "check"):
            rationale.append(R(SCodes.PF_CHECK_NOT_IN_RANGE))
            return ({"action": "check"}, rationale, "preflop_v0")
        if find_action(acts, "fold"):
            rationale.append(R(SCodes.PF_FOLD_NO_BET))
            return ({"action": "fold"}, rationale, "preflop_v0")

    # 2) 面对下注
    threshold = int(cfg.call_threshold_bb * bb)
    if (
        _in_call_range(obs.tags, obs.hand_class)
        and find_action(acts, "call")
        and to_call <= threshold
    ):
        rationale.append(
            R(
                SCodes.PF_CALL_THRESHOLD,
                data={"to_call": to_call, "threshold": threshold},
            )
        )
        return ({"action": "call"}, rationale, "preflop_v0")

    if find_action(acts, "fold"):
        rationale.append(
            R(
                SCodes.PF_FOLD_EXPENSIVE,
                data={"to_call": to_call, "threshold": threshold},
            )
        )
        return ({"action": "fold"}, rationale, "preflop_v0")

    if find_action(acts, "check"):
        rationale.append(R(SCodes.SAFE_CHECK))
        return ({"action": "check"}, rationale, "preflop_v0")

    raise ValueError("No safe suggestion")


def policy_postflop_v0_3(
    obs: Observation, cfg: PolicyConfig
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    """Postflop 策略 v0.3（纯函数）。

    - 无人下注线：flop 用最小试探注；turn/river 仅在具备一定摊牌价值（pair/Ax_suited）下注。
    - 面对下注线：按 pot-odds 与阈值决定 call 或 fold；范围内手牌使用更宽松阈值。
    """
    acts = list(obs.acts or [])
    if not acts:
        raise ValueError("No legal actions")

    rationale: list[dict[str, Any]] = [
        R(SCodes.PL_HEADER, data={"street": obs.street, "tags": list(obs.tags or [])}),
    ]

    to_call = int(obs.to_call if obs.to_call is not None else to_call_from_acts(acts))
    pot = int(obs.pot)

    # 无人下注线
    if to_call == 0:
        betlike = pick_betlike_action(acts)
        if (
            betlike
            and betlike.min is not None
            and betlike.max is not None
            and betlike.min <= betlike.max
        ):
            allow_bet = (obs.street == "flop") or (
                obs.street in {"turn", "river"}
                and ("pair" in (obs.tags or []) or obs.hand_class == "Ax_suited")
            )
            if allow_bet:
                amt = int(betlike.min)
                rationale.append(
                    R(
                        SCodes.PL_PROBE_BET,
                        msg=f"{obs.street} 无人下注线：以最小尺寸试探性下注。",
                        data={"chosen": amt},
                    )
                )
                return (
                    {"action": betlike.action, "amount": amt},
                    rationale,
                    "postflop_v0_3",
                )
        if find_action(acts, "check"):
            rationale.append(R(SCodes.PL_CHECK))
            return ({"action": "check"}, rationale, "postflop_v0_3")

    # 面对下注线：赔率判断
    denom = pot + to_call
    pot_odds = (to_call / denom) if denom > 0 else 1.0
    threshold = (
        cfg.pot_odds_threshold_callrange
        if _in_call_range(obs.tags, obs.hand_class)
        else cfg.pot_odds_threshold
    )

    if find_action(acts, "call") and pot_odds <= threshold:
        rationale.append(
            R(
                SCodes.PL_CALL_POTODDS,
                data={
                    "to_call": to_call,
                    "pot": pot,
                    "pot_odds": round(pot_odds, 4),
                    "threshold": threshold,
                },
            )
        )
        return ({"action": "call"}, rationale, "postflop_v0_3")

    if find_action(acts, "fold"):
        rationale.append(
            R(
                SCodes.PL_FOLD_POTODDS,
                data={
                    "to_call": to_call,
                    "pot": pot,
                    "pot_odds": round(pot_odds, 4),
                    "threshold": threshold,
                },
            )
        )
        return ({"action": "fold"}, rationale, "postflop_v0_3")

    # 兜底
    allin = find_action(acts, "allin")
    if allin:
        rationale.append(R(SCodes.PL_ALLIN_ONLY))
        return (
            {"action": "allin", "amount": allin.max or allin.min},
            rationale,
            "postflop_v0_3",
        )

    if find_action(acts, "check"):
        rationale.append(R(SCodes.SAFE_CHECK))
        return ({"action": "check"}, rationale, "postflop_v0_3")

    raise ValueError("No safe postflop suggestion")


__all__ = [
    "policy_preflop_v0",
    "policy_postflop_v0_3",
]


# --------- Preflop v1 (HU) ---------


def _conf_score(
    hit_range: bool = False,
    price_ok: bool = False,
    size_ok: bool = False,
    clamped: bool = False,
    fallback: bool = False,
    min_reopen_adjusted: bool = False,
) -> float:
    s = 0.5
    if hit_range:
        s += 0.3
    if price_ok or size_ok:
        s += 0.2
    if clamped:
        s -= 0.1
    if fallback:
        s -= 0.1
    if min_reopen_adjusted:
        # informational nudge, not a penalty
        s += 0.0
    return max(0.5, min(0.9, s))


def _bb_mult(v: float) -> int:
    return int(round(v))


def _pot_odds(to_call: int, pot_now: int) -> float:
    denom = pot_now + max(0, int(to_call))
    return (float(to_call) / float(denom)) if denom > 0 else 1.0


def _effective_stack_bb(obs: Observation) -> int:
    # 简化：使用 obs.bb 与 spr_bucket/pot_now 不足以精确栈深，近似返回较大值，依赖后续 clamp
    # 为 PR-1：我们只需要 cap 的保守界，避免溢出。
    # 近似：eff = max(10, round(spr*pot_now/bb))，spr_bucket 粗略映射
    if obs.spr_bucket == "low":
        return 10
    if obs.spr_bucket == "mid":
        return 20
    if obs.spr_bucket == "high":
        return 40
    # unknown → 20bb 近似
    return 20


def policy_preflop_v1(
    obs: Observation, cfg: PolicyConfig
) -> tuple[dict[str, Any], list[dict[str, Any]], str, dict[str, Any]]:
    acts = list(obs.acts or [])
    if not acts:
        raise ValueError("No legal actions")

    rationale: list[dict[str, Any]] = []

    from poker_core.suggest.context import SuggestContext

    ctx = obs.context or SuggestContext.build()

    combo = obs.combo or None
    if combo is None:
        rationale.append(R(SCodes.CFG_FALLBACK_USED))

    # Check if vs_table is effectively empty (fallback scenario)
    vs_tab = ctx.vs_table or {}
    bb_vs_sb = vs_tab.get("BB_vs_SB", {}) or {}
    sb_vs_bb_3bet = vs_tab.get("SB_vs_BB_3bet", {}) or {}
    if not bb_vs_sb and not sb_vs_bb_3bet:
        rationale.append(R(SCodes.CFG_FALLBACK_USED))
    # Also check if the loaded version is 0 (mocked empty table)
    if ctx.versions.get("vs", 1) == 0:
        rationale.append(R(SCodes.CFG_FALLBACK_USED))

    modes = ctx.modes.get("HU", {}) if isinstance(ctx.modes, dict) else {}
    open_tab = ctx.open_table
    vs_tab = ctx.vs_table

    defend_ip = float(modes.get("defend_threshold_ip", 0.42))
    defend_oop = float(modes.get("defend_threshold_oop", 0.38))

    to_call = int(obs.to_call if obs.to_call is not None else to_call_from_acts(acts))
    bb = int(obs.bb or 50)
    pot_now = int(getattr(obs, "pot_now", 0))
    price = _pot_odds(to_call, pot_now)

    decision = decide_sb_vs_threebet(obs, ctx, cfg)
    if decision:
        suggested, decision_meta, decision_rationale = decision.resolve(obs, acts, cfg)
        return suggested, rationale + decision_rationale, "preflop_v1", dict(decision_meta)

    decision = decide_sb_open(obs, ctx, cfg)
    if decision:
        suggested, decision_meta, decision_rationale = decision.resolve(obs, acts, cfg)
        return suggested, rationale + decision_rationale, "preflop_v1", dict(decision_meta)

    decision = decide_bb_defend(obs, ctx, cfg)
    if decision:
        suggested, decision_meta, decision_rationale = decision.resolve(obs, acts, cfg)
        return suggested, rationale + decision_rationale, "preflop_v1", dict(decision_meta)

    # Fallbacks for edge cases not covered by dedicated helpers
    is_sb_first_in = obs.street == "preflop" and bool(obs.first_to_act)
    if is_sb_first_in:
        open_set = set(open_tab.get("SB", set()) or set())
        betlike = pick_betlike_action(acts)
        if combo in open_set and not betlike:
            rationale.append(R(SCodes.PF_NO_LEGAL_RAISE))
        if find_action(acts, "call") and to_call > 0 and to_call <= bb:
            rationale.append(R(SCodes.PF_LIMP_COMPLETE_BLIND))
            return {"action": "call"}, rationale, "preflop_v1", {}
        if to_call == 0 and find_action(acts, "check"):
            return {"action": "check"}, rationale, "preflop_v1", {}

    if obs.street == "preflop" and to_call > 0:
        bucket = bucket_facing_size(max(0.0, to_call / float(bb or 1)))
        ip_like = bool(obs.last_to_act)
        defend_thr = defend_ip if ip_like else defend_oop
        node_vs = (vs_tab.get("BB_vs_SB", {}) or {}).get(bucket, {}) or {}
        call_set = set(node_vs.get("call", set()) or set())
        reraise_set = set(node_vs.get("reraise", set()) or set())

        is_out_of_range = combo and combo not in call_set and combo not in reraise_set
        vs_table_empty = not call_set and not reraise_set

        if is_out_of_range:
            rationale.append(
                R(
                    SCodes.PF_DEFEND_PRICE_BAD,
                    data={
                        "pot_odds": round(price, 4),
                        "thr": defend_thr,
                        "bucket": bucket,
                        "reason": "out_of_range",
                    },
                )
            )

        # When vs_table is empty, be more conservative with out-of-range hands
        if (
            find_action(acts, "call")
            and price <= defend_thr
            and not (vs_table_empty and is_out_of_range)
        ):
            rationale.append(
                R(
                    SCodes.PF_DEFEND_PRICE_OK,
                    data={"pot_odds": round(price, 4), "thr": defend_thr, "bucket": bucket},
                )
            )
            meta = {"bucket": bucket, "pot_odds": round(price, 4)}
            return {"action": "call"}, rationale, "preflop_v1", meta
        if find_action(acts, "fold"):
            rationale.append(
                R(
                    SCodes.PF_DEFEND_PRICE_BAD,
                    data={"pot_odds": round(price, 4), "thr": defend_thr, "bucket": bucket},
                )
            )
            return {"action": "fold"}, rationale, "preflop_v1", {"bucket": bucket}

    # Final fallback: call if pot odds are decent, otherwise fold/check
    if find_action(acts, "call") and price <= 0.5:  # Call if pot odds <= 50%
        rationale.append(R(SCodes.PF_DEFEND_PRICE_OK, data={"pot_odds": round(price, 4)}))
        return {"action": "call"}, rationale, "preflop_v1", {"pot_odds": round(price, 4)}
    if find_action(acts, "fold"):
        return {"action": "fold"}, rationale, "preflop_v1", {}
    if find_action(acts, "check"):
        return {"action": "check"}, rationale, "preflop_v1", {}
    raise ValueError("No safe preflop v1 suggestion")


__all__.append("policy_preflop_v1")


# --------- Flop v1 (HU, single-raised only; role+MDF aligned) ---------


def _match_rule_with_trace(
    node: dict[str, Any], keys: list[str]
) -> tuple[dict[str, Any] | None, str]:
    """Depth-first lookup with defaults fallback and trace of matched path."""
    cur: Any = node
    path: list[str] = []
    try:
        for k in keys:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
                path.append(k)
            elif isinstance(cur, dict) and "defaults" in cur:
                cur = cur["defaults"]
                path.append(f"defaults:{k}")
            else:
                return None, "/".join(path)
        if isinstance(cur, dict) and ("action" in cur or "size_tag" in cur):
            return cur, "/".join(path)
    except Exception:
        return None, "/".join(path)
    return None, "/".join(path)


def policy_flop_v1(
    obs: Observation, cfg: PolicyConfig
) -> tuple[dict[str, Any], list[dict[str, Any]], str, dict[str, Any]]:
    acts = list(obs.acts or [])
    if not acts:
        raise ValueError("No legal actions")

    rationale: list[dict[str, Any]] = []

    from poker_core.suggest.context import SuggestContext

    ctx = obs.context or SuggestContext.build()

    # Load rules (strategy-aware)
    rules, ver = get_flop_rules()

    # Pot type: support single_raised; limped added in v1.1; threebet TBD
    pot_type = getattr(obs, "pot_type", "single_raised") or "single_raised"
    if pot_type not in (rules or {}):
        rationale.append(R(SCodes.CFG_FALLBACK_USED))

    # Derived inputs
    ip_key = "ip" if bool(obs.ip) else "oop"
    texture = obs.board_texture or "na"
    spr = obs.spr_bucket or "na"
    role = obs.role or "na"
    if pot_type == "limped":
        role = "na"

    # Facing a bet?
    to_call = int(obs.to_call or 0)
    pot_now = int(obs.pot_now or 0)
    denom = pot_now + max(0, to_call)
    pot_odds = (to_call / denom) if denom > 0 else 1.0
    mdf = 1.0 - pot_odds

    # Meta to return (teaching fields)
    meta: dict[str, Any] = {
        "size_tag": None,
        "role": role,
        "texture": texture,
        "spr_bucket": spr,
        "mdf": round(mdf, 4),
        "pot_odds": round(pot_odds, 4),
        "facing_size_tag": getattr(obs, "facing_size_tag", "na"),
        "range_adv": bool(getattr(obs, "range_adv", False)),
        "nut_adv": bool(getattr(obs, "nut_adv", False)),
        "rules_ver": ver,
        "plan": None,
    }

    # 1) No bet yet: prefer c-bet on dry boards when PFR
    if to_call == 0:
        node = None
        if pot_type == "limped":
            node, rule_path = _match_rule_with_trace(
                rules,
                [
                    pot_type,
                    "role",
                    "na",
                    ip_key,
                    texture,
                    spr,
                    str(obs.hand_class or "unknown"),
                ],
            )
            meta.setdefault("rule_path", rule_path)
        else:
            node, rule_path = _match_rule_with_trace(
                rules,
                [
                    pot_type,
                    "role",
                    role,
                    ip_key,
                    texture,
                    spr,
                    str(obs.hand_class or "unknown"),
                ],
            )
            meta.setdefault("rule_path", rule_path)

        if node:
            action = str(node.get("action") or "bet")
            size_tag = str(node.get("size_tag") or "third")
            meta["rule_path"] = rule_path
            meta["size_tag"] = size_tag
            plan_str = node.get("plan")
            if isinstance(plan_str, str) and plan_str:
                meta["plan"] = plan_str
            if action in {"bet", "raise"}:
                decision = Decision(
                    action=action,
                    sizing=SizeSpec.tag(size_tag),
                    meta={"size_tag": size_tag},
                )
                suggested, decision_meta, decision_rationale = decision.resolve(obs, acts, cfg)
                meta.update(decision_meta)
                if bool(meta["range_adv"]) and size_tag == "third":
                    rationale.append(R(SCodes.FL_RANGE_ADV_SMALL_BET))
                elif bool(meta["nut_adv"]) and size_tag in {"two_third", "pot"}:
                    rationale.append(R(SCodes.FL_NUT_ADV_POLAR))
                else:
                    rationale.append(R(SCodes.FL_DRY_CBET_THIRD))
                if (
                    obs.spr_bucket == "le3"
                    and size_tag in {"two_third", "pot"}
                    and (obs.hand_class in {HC_VALUE, HC_OP_TPTK})
                ):
                    rationale.append(R(SCodes.FL_LOW_SPR_VALUE_UP))
                rationale.extend(decision_rationale)
                return suggested, rationale, "flop_v1", meta
            if action == "check" and find_action(acts, "check"):
                rationale.append(R(SCodes.FL_DELAYED_CBET_PLAN))
                meta["rule_path"] = rule_path
                decision = Decision(action="check", meta={})
                suggested, decision_meta, decision_rationale = decision.resolve(obs, acts, cfg)
                meta.update(decision_meta)
                rationale.extend(decision_rationale)
                return suggested, rationale, "flop_v1", meta

        # Fallback defaults by texture
        if role == "pfr" and texture == "dry" and pick_betlike_action(acts):
            decision = Decision(
                action="bet",
                sizing=SizeSpec.tag("third"),
                meta={"size_tag": "third"},
            )
            suggested, decision_meta, decision_rationale = decision.resolve(obs, acts, cfg)
            meta.update(decision_meta)
            rationale.append(R(SCodes.FL_RANGE_ADV_SMALL_BET))
            rationale.extend(decision_rationale)
            return suggested, rationale, "flop_v1", meta
        if find_action(acts, "check"):
            rationale.append(R(SCodes.FL_CHECK_RANGE))
            decision = Decision(action="check", meta={})
            suggested, decision_meta, decision_rationale = decision.resolve(obs, acts, cfg)
            meta.update(decision_meta)
            rationale.extend(decision_rationale)
            return suggested, rationale, "flop_v1", meta

    # 2) Facing a bet: first check JSON-driven value-raise; otherwise show MDF/pot_odds and choose simple line
    fst = getattr(obs, "facing_size_tag", "na")
    allow_value_raise = ctx.flags.enable_flop_value_raise

    # JSON-driven value raise: lookup facing rules under current class node
    try:
        # resolve role for base path first (limped uses role='na')
        _role = role if pot_type != "limped" else "na"
        base_path = "/".join(
            [
                pot_type,
                f"role:{_role}",
                ip_key,
                texture,
                spr,
            ]
        )
        meta.setdefault("rule_path", base_path)

        if (
            allow_value_raise
            and str(obs.hand_class) == HC_VALUE
            and fst in {"third", "half", "two_third+"}
        ):
            # _role already resolved above
            # traverse dicts without defaults for precision
            pot_node = (rules or {}).get(pot_type, {})
            role_node = (pot_node.get("role", {}) or {}).get(_role, {})
            pos_node = (role_node.get(ip_key, {}) or {}).get(texture, {})
            spr_node = pos_node.get(spr, {}) or {}
            cls_node = spr_node.get("value_two_pair_plus", {}) or {}
            facing = cls_node.get("facing") if isinstance(cls_node, dict) else None
            if isinstance(facing, dict):
                key = "two_third_plus" if fst == "two_third+" else fst
                fr = facing.get(key)
                if isinstance(fr, dict) and fr.get("action") in {
                    "raise",
                    "call",
                    "fold",
                }:
                    meta["rule_path"] = "/".join(
                        [
                            pot_type,
                            f"role:{_role}",
                            ip_key,
                            texture,
                            spr,
                            "value_two_pair_plus",
                            f"facing.{key}",
                        ]
                    )
                    action = str(fr.get("action"))
                    plan = fr.get("plan")
                    if plan:
                        meta["plan"] = plan
                    if action == "raise" and find_action(acts, "raise"):
                        st = str(fr.get("size_tag") or "half")
                        decision = Decision(
                            action="raise",
                            sizing=SizeSpec.tag(st),
                            meta={"size_tag": st},
                        )
                        suggested, decision_meta, decision_rationale = decision.resolve(
                            obs, acts, cfg
                        )
                        meta.update(decision_meta)
                        rationale.append(R(SCodes.FL_RAISE_VALUE))
                        rationale.extend(decision_rationale)
                        return suggested, rationale, "flop_v1", meta
                    if action == "call" and find_action(acts, "call"):
                        decision = Decision(action="call", meta={})
                        suggested, decision_meta, decision_rationale = decision.resolve(
                            obs, acts, cfg
                        )
                        meta.update(decision_meta)
                        rationale.extend(decision_rationale)
                        return suggested, rationale, "flop_v1", meta
                    if action == "fold" and find_action(acts, "fold"):
                        decision = Decision(action="fold", meta={})
                        suggested, decision_meta, decision_rationale = decision.resolve(
                            obs, acts, cfg
                        )
                        meta.update(decision_meta)
                        rationale.extend(decision_rationale)
                        return suggested, rationale, "flop_v1", meta
    except Exception:
        pass

    # Default MDF 展示
    rationale.append(
        R(
            SCodes.FL_MDF_DEFEND,
            data={"mdf": meta["mdf"], "pot_odds": meta["pot_odds"], "facing": fst},
        )
    )
    # threebet: add light value-raise and semi-bluff raise stubs
    if getattr(obs, "pot_type", "single_raised") == "threebet":
        # value raise vs small/half when we hold two_pair+ (OOP/IP)
        if (
            fst in {"third", "half"}
            and getattr(obs, "hand_class", "") in {HC_VALUE}
            and find_action(acts, "raise")
        ):
            decision = Decision(
                action="raise",
                sizing=SizeSpec.tag("two_third"),
                meta={"size_tag": "two_third"},
            )
            suggested, decision_meta, decision_rationale = decision.resolve(obs, acts, cfg)
            meta.update(decision_meta)
            rationale.append(R(SCodes.FL_RAISE_VALUE))
            rationale.extend(decision_rationale)
            return suggested, rationale, "flop_v1", meta
        # semi-bluff raise vs small when we have strong_draw (IP preferred but allow both)
        if (
            fst in {"third", "half"}
            and getattr(obs, "hand_class", "") in {HC_STRONG_DRAW}
            and find_action(acts, "raise")
        ):
            decision = Decision(
                action="raise",
                sizing=SizeSpec.tag("half"),
                meta={"size_tag": "half"},
            )
            suggested, decision_meta, decision_rationale = decision.resolve(obs, acts, cfg)
            meta.update(decision_meta)
            rationale.append(R(SCodes.FL_RAISE_SEMI_BLUFF))
            rationale.extend(decision_rationale)
            return suggested, rationale, "flop_v1", meta
    if fst in {"third", "half"} and find_action(acts, "call"):
        if (
            allow_value_raise
            and getattr(obs, "spr_bucket", "") == "le3"
            and getattr(obs, "hand_class", "") in {HC_OP_TPTK}
            and find_action(acts, "raise")
        ):
            decision = Decision(
                action="raise",
                sizing=SizeSpec.tag("two_third"),
                meta={"size_tag": "two_third"},
            )
            suggested, decision_meta, decision_rationale = decision.resolve(obs, acts, cfg)
            meta.update(decision_meta)
            rationale.append(R(SCodes.FL_RAISE_VALUE))
            rationale.extend(decision_rationale)
            if not meta.get("plan"):
                meta["plan"] = "低 SPR：强顶对面对小注→价值加注"
            return suggested, rationale, "flop_v1", meta
        decision = Decision(action="call", meta={})
        suggested, decision_meta, decision_rationale = decision.resolve(obs, acts, cfg)
        meta.update(decision_meta)
        rationale.extend(decision_rationale)
        return suggested, rationale, "flop_v1", meta
    # vs large sizes: if we have any raise path and nut_adv, allow raise stub (service will clamp)
    if fst == "two_third+" and bool(meta["nut_adv"]) and find_action(acts, "raise"):
        decision = Decision(
            action="raise",
            sizing=SizeSpec.tag("two_third"),
            meta={"size_tag": "two_third"},
        )
        suggested, decision_meta, decision_rationale = decision.resolve(obs, acts, cfg)
        if not meta.get("plan"):
            meta["plan"] = "vs small/half → call; vs two_third+ → raise"
        meta.update(decision_meta)
        rationale.append(R(SCodes.FL_RAISE_SEMI_BLUFF))
        rationale.extend(decision_rationale)
        return suggested, rationale, "flop_v1", meta
    if fst == "two_third+" and find_action(acts, "fold"):
        hand_class = getattr(obs, "hand_class", "")
        strong_classes = {HC_VALUE, HC_STRONG_DRAW, HC_OP_TPTK}
        if hand_class not in strong_classes and not bool(meta["nut_adv"]):
            if pot_odds > 0.40:
                rationale.append(
                    R(
                        SCodes.PL_FOLD_POTODDS,
                        data={
                            "facing": fst,
                            "pot_odds": round(pot_odds, 3),
                            "hand_class": hand_class,
                        },
                    )
                )
                decision = Decision(action="fold", meta={})
                suggested, decision_meta, decision_rationale = decision.resolve(obs, acts, cfg)
                meta.update(decision_meta)
                rationale.extend(decision_rationale)
                return suggested, rationale, "flop_v1", meta
    if find_action(acts, "call"):
        decision = Decision(action="call", meta={})
        suggested, decision_meta, decision_rationale = decision.resolve(obs, acts, cfg)
        meta.update(decision_meta)
        rationale.extend(decision_rationale)
        return suggested, rationale, "flop_v1", meta
    if find_action(acts, "fold"):
        decision = Decision(action="fold", meta={})
        suggested, decision_meta, decision_rationale = decision.resolve(obs, acts, cfg)
        meta.update(decision_meta)
        rationale.extend(decision_rationale)
        return suggested, rationale, "flop_v1", meta

    # Last resort
    if find_action(acts, "check"):
        decision = Decision(action="check", meta={})
        suggested, decision_meta, decision_rationale = decision.resolve(obs, acts, cfg)
        meta.update(decision_meta)
        rationale.extend(decision_rationale)
        return suggested, rationale, "flop_v1", meta
    raise ValueError("No safe flop v1 suggestion")


__all__.append("policy_flop_v1")


# --------- Turn/River v1 (HU, minimal teaching-first) ---------


def _policy_postflop_generic(
    street: str, obs: Observation, cfg: PolicyConfig
) -> tuple[dict[str, Any], list[dict[str, Any]], str, dict[str, Any]]:
    acts = list(obs.acts or [])
    if not acts:
        raise ValueError("No legal actions")

    rules, ver = get_turn_rules() if street == "turn" else get_river_rules()

    to_call = int(obs.to_call or 0)
    pot_now = int(obs.pot_now or 0)
    denom = pot_now + max(0, to_call)
    pot_odds = (to_call / denom) if denom > 0 else 1.0
    mdf = 1.0 - pot_odds

    ip_key = "ip" if bool(obs.ip) else "oop"
    texture = getattr(obs, "board_texture", "na") or "na"
    spr_raw = getattr(obs, "spr_bucket", "na") or "na"
    spr = _spr_key_for_rules(spr_raw)
    role = getattr(obs, "role", "na") or "na"
    pot_type = getattr(obs, "pot_type", "single_raised") or "single_raised"

    rationale: list[dict[str, Any]] = []
    meta: dict[str, Any] = {
        "size_tag": None,
        "role": role,
        "texture": texture,
        "spr_bucket": spr,
        "mdf": round(mdf, 4),
        "pot_odds": round(pot_odds, 4),
        "facing_size_tag": getattr(obs, "facing_size_tag", "na"),
        "rules_ver": ver,
        "plan": None,
    }

    def _lookup_node() -> tuple[dict[str, Any] | None, str]:
        keys = [
            pot_type,
            "role",
            role if pot_type != "limped" else "na",
            ip_key,
            texture,
            spr,
            str(obs.hand_class or "unknown"),
        ]
        cur: Any = rules
        path: list[str] = []
        try:
            for k in keys:
                if isinstance(cur, dict) and k in cur:
                    cur = cur[k]
                    path.append(k)
                elif isinstance(cur, dict) and "defaults" in cur:
                    cur = cur["defaults"]
                    path.append(f"defaults:{k}")
                else:
                    return None, "/".join(path)
                # Early stop if current node already specifies action/sizing
                if isinstance(cur, dict) and ("action" in cur or "size_tag" in cur):
                    return cur, "/".join(path)
            if isinstance(cur, dict) and ("action" in cur or "size_tag" in cur):
                return cur, "/".join(path)
        except Exception:
            return None, "/".join(path)
        return None, "/".join(path)

    # 1) No bet yet: use table or safe default
    if to_call == 0:
        node, rule_path = _lookup_node()
        if node:
            action = str(node.get("action") or "bet")
            size_tag = str(node.get("size_tag") or "third")
            meta["rule_path"] = rule_path
            meta["size_tag"] = size_tag
            plan_str = node.get("plan")
            if isinstance(plan_str, str) and plan_str:
                meta["plan"] = plan_str
            if action in {"bet", "raise"} and (
                find_action(acts, action) or pick_betlike_action(acts)
            ):
                decision = Decision(
                    action=action, sizing=SizeSpec.tag(size_tag), meta={"size_tag": size_tag}
                )
                suggested, dmeta, drat = decision.resolve(obs, acts, cfg)
                meta.update(dmeta)
                return suggested, rationale + drat, f"{street}_v1", meta
            if action == "check" and find_action(acts, "check"):
                decision = Decision(action="check", meta={})
                suggested, dmeta, drat = decision.resolve(obs, acts, cfg)
                meta.update(dmeta)
                return suggested, rationale + drat, f"{street}_v1", meta
        # fallback
        if pick_betlike_action(acts):
            decision = Decision(
                action="bet", sizing=SizeSpec.tag("third"), meta={"size_tag": "third"}
            )
            suggested, dmeta, drat = decision.resolve(obs, acts, cfg)
            meta.update(dmeta)
            return suggested, rationale + drat, f"{street}_v1", meta
        if find_action(acts, "check"):
            decision = Decision(action="check", meta={})
            suggested, dmeta, drat = decision.resolve(obs, acts, cfg)
            meta.update(dmeta)
            return suggested, rationale + drat, f"{street}_v1", meta

    # 2) Facing a bet: expose MDF/pot_odds; choose simple line
    rationale.append(
        R(
            SCodes.FL_MDF_DEFEND,
            data={
                "mdf": meta["mdf"],
                "pot_odds": meta["pot_odds"],
                "facing": meta["facing_size_tag"],
            },
        )
    )
    # value raise stub: when hand_class indicates value (inherit flop class semantics if provided)
    if (
        getattr(obs, "hand_class", "") in {HC_VALUE}
        and find_action(acts, "raise")
        and meta["facing_size_tag"] in {"third", "half"}
    ):
        decision = Decision(
            action="raise", sizing=SizeSpec.tag("two_third"), meta={"size_tag": "two_third"}
        )
        suggested, dmeta, drat = decision.resolve(obs, acts, cfg)
        meta.update(dmeta)
        rationale.append(R(SCodes.FL_RAISE_VALUE))
        return suggested, rationale + drat, f"{street}_v1", meta
    if meta["facing_size_tag"] in {"third", "half"} and find_action(acts, "call"):
        decision = Decision(action="call", meta={})
        suggested, dmeta, drat = decision.resolve(obs, acts, cfg)
        meta.update(dmeta)
        return suggested, rationale + drat, f"{street}_v1", meta
    if find_action(acts, "call"):
        decision = Decision(action="call", meta={})
        suggested, dmeta, drat = decision.resolve(obs, acts, cfg)
        meta.update(dmeta)
        return suggested, rationale + drat, f"{street}_v1", meta
    if find_action(acts, "fold"):
        decision = Decision(action="fold", meta={})
        suggested, dmeta, drat = decision.resolve(obs, acts, cfg)
        meta.update(dmeta)
        return suggested, rationale + drat, f"{street}_v1", meta
    if find_action(acts, "check"):
        decision = Decision(action="check", meta={})
        suggested, dmeta, drat = decision.resolve(obs, acts, cfg)
        meta.update(dmeta)
        return suggested, rationale + drat, f"{street}_v1", meta
    raise ValueError(f"No safe {street} v1 suggestion")


def policy_turn_v1(obs: Observation, cfg: PolicyConfig):
    return _policy_postflop_generic("turn", obs, cfg)


def policy_river_v1(obs: Observation, cfg: PolicyConfig):
    return _policy_postflop_generic("river", obs, cfg)


__all__.extend(["policy_turn_v1", "policy_river_v1"])


def _spr_key_for_rules(s: str) -> str:
    """Map observation SPR buckets (low/mid/high) to config keys (le3/3to6/ge6)."""
    m = {"low": "le3", "mid": "3to6", "high": "ge6"}
    return m.get(str(s or "").lower(), str(s or "na"))
