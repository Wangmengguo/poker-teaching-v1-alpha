"""Preflop helper modules extracted from policy_preflop_v1."""

from __future__ import annotations

from dataclasses import dataclass

from poker_core.domain.actions import LegalAction
from poker_core.suggest.codes import SCodes
from poker_core.suggest.codes import mk_rationale as R
from poker_core.suggest.context import SuggestContext
from poker_core.suggest.decision import Decision, SizeSpec
from poker_core.suggest.preflop_tables import bucket_facing_size
from poker_core.suggest.types import Observation, PolicyConfig
from poker_core.suggest.utils import (
    find_action,
    pick_betlike_action,
)

from .calculators import pot_odds


@dataclass
class PreflopDecision:
    decision: Decision
    rationale: list[dict]
    meta: dict[str, int | float | str]

    def resolve(
        self, obs: Observation, acts: list[LegalAction], cfg: PolicyConfig
    ) -> tuple[dict[str, int | str], dict, list[dict]]:
        suggested, decision_meta, decision_rationale = self.decision.resolve(obs, acts, cfg)
        meta = {**decision_meta, **(self.meta or {})}
        rationale = list(self.rationale or []) + list(decision_rationale or [])
        return suggested, meta, rationale


def _mode_thr(ctx: SuggestContext) -> tuple[float, float]:
    modes = ctx.modes.get("HU", {}) if isinstance(ctx.modes, dict) else {}
    small_le = float(modes.get("threebet_bucket_small_le", 9.0))
    mid_le = float(modes.get("threebet_bucket_mid_le", 11.0))
    return small_le, mid_le


def _plan_sb_rfi(ctx: SuggestContext, combo: str) -> str:
    small_le, mid_le = _mode_thr(ctx)
    vs_sb = ctx.vs_table.get("SB_vs_BB_3bet", {}) or {}
    fourbet_set = set()
    call_set = set()
    for bkt in ("small", "mid", "large"):
        node = vs_sb.get(bkt, {}) or {}
        fourbet_set |= set(node.get("fourbet") or node.get("reraise") or [])
        call_set |= set(node.get("call") or [])
    if combo in fourbet_set:
        return f"若被 3bet：≤{int(small_le)}bb 四bet；≤{int(mid_le)}bb 四bet/跟注；更大 保守处理。"
    if combo in call_set:
        return f"若被 3bet：≤{int(small_le)}bb 跟注；≤{int(mid_le)}bb 跟注；更大 弃牌。"
    return "若被 3bet：小/中档可考虑跟注；更大 弃牌。"


def decide_sb_open(
    obs: Observation, ctx: SuggestContext, cfg: PolicyConfig
) -> PreflopDecision | None:
    """SB first-in open sizing when combo in range."""

    if obs.street != "preflop":
        return None
    if obs.pot_type != "limped" or not obs.first_to_act:
        return None
    # 允许 SB 盲注差额（to_call <= 1bb）仍视为首入开局
    try:
        to_call = float(obs.to_call or 0)
        bb = float(obs.bb or 0)
    except (TypeError, ValueError):
        return None
    if to_call > max(bb, 0.0):
        return None

    betlike = pick_betlike_action(obs.acts)
    if not betlike:
        return None

    combo = obs.combo or ""
    open_set = set(ctx.open_table.get("SB", set()) or set())
    if combo not in open_set:
        return None

    modes = ctx.modes.get("HU", {}) if isinstance(ctx.modes, dict) else {}
    open_bb = float(modes.get("open_bb", cfg.open_size_bb))

    rationale = [R(SCodes.PF_OPEN_RANGE_HIT, data={"open_bb": open_bb})]
    plan_str = _plan_sb_rfi(ctx, combo)
    decision = Decision(
        action=betlike.action,
        sizing=SizeSpec.bb(open_bb),
        meta={"open_bb": open_bb, "plan": plan_str},
    )
    return PreflopDecision(decision=decision, rationale=rationale, meta={})


def decide_bb_defend(
    obs: Observation, ctx: SuggestContext, cfg: PolicyConfig
) -> PreflopDecision | None:
    """BB facing SB open: choose 3bet/call/fold."""

    if obs.street != "preflop" or obs.to_call <= 0:
        return None
    if not obs.last_to_act:
        return None

    modes = ctx.modes.get("HU", {}) if isinstance(ctx.modes, dict) else {}
    defend_ip = float(modes.get("defend_threshold_ip", 0.42))
    defend_oop = float(modes.get("defend_threshold_oop", 0.38))
    reraise_ip_mult = float(modes.get("reraise_ip_mult", 3.0))
    reraise_oop_mult = float(modes.get("reraise_oop_mult", 3.5))
    reraise_oop_offset = float(modes.get("reraise_oop_offset", 0.5))
    cap_ratio = float(modes.get("cap_ratio", 0.9))

    ip_like = bool(obs.last_to_act)
    defend_thr = defend_ip if ip_like else defend_oop

    bucket = bucket_facing_size(obs.to_call / float(obs.bb))
    vs_node = (ctx.vs_table.get("BB_vs_SB", {}) or {}).get(bucket, {}) or {}
    call_set = set(vs_node.get("call", set()) or set())
    reraise_set = set(vs_node.get("reraise", set()) or set())

    combo = obs.combo or ""
    price = pot_odds(obs.to_call, obs.pot_now)
    rationale: list[dict] = []

    if combo in reraise_set and find_action(obs.acts, "raise"):
        to_call_bb = obs.to_call / float(obs.bb)
        open_to_bb = to_call_bb + 1.0
        mult = reraise_ip_mult if ip_like else reraise_oop_mult
        target_to_bb = round(open_to_bb * mult + (0.0 if ip_like else reraise_oop_offset))
        cap_bb = _cap_bb(obs, cap_ratio)
        reraise_to_bb = min(cap_bb, target_to_bb)
        rationale.append(R(SCodes.PF_DEFEND_3BET, data={"bucket": bucket}))
        decision = Decision(
            action="raise",
            sizing=SizeSpec.bb(reraise_to_bb),
            meta={
                "bucket": bucket,
                "reraise_to_bb": reraise_to_bb,
                "cap_bb": cap_bb,
                "pot_odds": round(price, 4),
                "plan": "若遭四bet 默认弃牌；仅 QQ+/AK 继续。",
            },
            min_reopen_code=SCodes.PF_DEFEND_3BET_MIN_RAISE_ADJUSTED,
        )
        return PreflopDecision(decision, rationale, meta={})

    if combo in call_set and find_action(obs.acts, "call"):
        if price <= defend_thr:
            rationale.append(
                R(
                    SCodes.PF_DEFEND_PRICE_OK,
                    data={"pot_odds": round(price, 4), "thr": defend_thr, "bucket": bucket},
                )
            )
            decision = Decision(
                action="call",
                meta={
                    "bucket": bucket,
                    "pot_odds": round(price, 4),
                    "plan": "进入翻牌：按 Flop v1（纹理+MDF）继续。",
                },
            )
            return PreflopDecision(decision, rationale, meta={})
        else:
            rationale.append(
                R(
                    SCodes.PF_DEFEND_PRICE_BAD,
                    data={"pot_odds": round(price, 4), "thr": defend_thr, "bucket": bucket},
                )
            )
            if find_action(obs.acts, "fold"):
                meta = {"bucket": bucket, "pot_odds": round(price, 4)}
                decision = Decision(action="fold", meta=meta)
                return PreflopDecision(decision, rationale, meta={})

    return None


def decide_sb_vs_threebet(
    obs: Observation, ctx: SuggestContext, cfg: PolicyConfig
) -> PreflopDecision | None:
    """SB facing BB 3bet (optional 4bet module)."""

    if obs.street != "preflop" or obs.to_call <= 0:
        return None
    if obs.first_to_act:  # first-in case already handled elsewhere
        return None
    # Only handle SB vs BB 3bet scenario
    if obs.last_to_act:  # BB should be last to act in SB vs BB 3bet
        return None

    combo = obs.combo or ""
    vs_sb = ctx.vs_table.get("SB_vs_BB_3bet", {}) or {}

    threebet_to_bb = _threebet_to_bb(obs)
    bucket = _bucket_threebet_to(threebet_to_bb, ctx)
    node = vs_sb.get(bucket, {}) or {}
    fourbet_set = set(node.get("fourbet", set()) or node.get("reraise", set()) or set())
    call_set = set(node.get("call", set()) or set())

    rationale: list[dict] = []

    if combo in fourbet_set and find_action(obs.acts, "raise"):
        modes = ctx.modes.get("HU", {}) if isinstance(ctx.modes, dict) else {}
        fourbet_ip_mult = float(modes.get("fourbet_ip_mult", 2.2))
        cap_ratio_4b = float(modes.get("cap_ratio_4b", modes.get("cap_ratio", 0.9)))
        cap_bb = _cap_bb(obs, cap_ratio_4b)
        target_to_bb = round(max(0.0, threebet_to_bb) * fourbet_ip_mult)
        fourbet_to_bb = max(0, min(cap_bb, target_to_bb))
        rationale.append(
            R(
                SCodes.PF_ATTACK_4BET,
                data={"bucket": bucket, "threebet_to_bb": round(threebet_to_bb, 2)},
            )
        )
        small_le, mid_le = _mode_thr(ctx)
        decision = Decision(
            action="raise",
            sizing=SizeSpec.bb(fourbet_to_bb),
            meta={
                "fourbet_to_bb": int(fourbet_to_bb),
                "bucket": bucket,
                "threebet_to_bb": round(threebet_to_bb, 2),
                "cap_bb": cap_bb,
                "combo": combo,
                "plan": f"面对 3bet：≤{int(small_le)}bb 4bet 到 {int(fourbet_to_bb)}bb；≤{int(mid_le)}bb 4bet；更大 谨慎/弃牌。",
            },
            min_reopen_code=SCodes.PF_ATTACK_4BET_MIN_RAISE_ADJUSTED,
        )
        return PreflopDecision(decision, rationale, meta={})

    if combo in call_set and find_action(obs.acts, "call"):
        rationale.append(R(SCodes.PF_DEFEND_PRICE_OK, data={"bucket": bucket}))
        small_le, mid_le = _mode_thr(ctx)
        decision = Decision(
            action="call",
            meta={
                "bucket": bucket,
                "plan": f"面对 3bet：≤{int(small_le)}bb 跟注；≤{int(mid_le)}bb 跟注；更大 弃牌。",
            },
        )
        return PreflopDecision(decision, rationale, meta={})

    # Fallback: call if pot odds are good or 3bet is small
    if find_action(obs.acts, "call"):
        pot_odds = obs.to_call / (obs.pot_now + obs.to_call) if obs.pot_now and obs.to_call else 0
        modes = ctx.modes.get("HU", {}) if isinstance(ctx.modes, dict) else {}
        thr = float(modes.get("defend_threshold_ip", 0.42))
        # Call if pot odds <= threshold or 3bet is very small (< 2.2bb)
        if pot_odds <= thr or threebet_to_bb < 2.2:
            rationale.append(
                R(
                    SCodes.PF_DEFEND_PRICE_OK,
                    data={"pot_odds": round(pot_odds, 3), "bucket": bucket, "thr": thr},
                )
            )
            decision = Decision(
                action="call", meta={"bucket": bucket, "pot_odds": round(pot_odds, 4)}
            )
            return PreflopDecision(decision, rationale, meta={})

    if find_action(obs.acts, "fold"):
        rationale.append(R(SCodes.PF_FOLD_EXPENSIVE, data={"bucket": bucket}))
        decision = Decision(action="fold", meta={"bucket": bucket})
        return PreflopDecision(decision, rationale, meta={})

    return None


def _cap_bb(obs: Observation, cap_ratio: float) -> int:
    if cap_ratio <= 0:
        return 999
    eff_bb = _effective_stack_bb(obs)
    return int(eff_bb * cap_ratio)


def _effective_stack_bb(obs: Observation) -> int:
    bucket = getattr(obs, "spr_bucket", "na")
    if bucket == "low":
        return 10
    if bucket == "mid":
        return 20
    if bucket == "high":
        return 40
    return 20


def _threebet_to_bb(obs: Observation) -> float:
    to_call = max(0, int(obs.to_call or 0))
    pot_now = max(0, int(obs.pot_now or 0))
    tc = float(to_call)
    pn = float(pot_now)
    if pn < tc:
        return 0.0
    i_opp = (pn + tc) / 2.0
    return i_opp / float(obs.bb or 1)


def _bucket_threebet_to(value: float, ctx: SuggestContext) -> str:
    modes = ctx.modes.get("HU", {}) if isinstance(ctx.modes, dict) else {}
    small_le = float(modes.get("threebet_bucket_small_le", 9.0))
    mid_le = float(modes.get("threebet_bucket_mid_le", 11.0))
    if value <= small_le:
        return "small"
    if value <= mid_le:
        return "mid"
    return "large"


__all__ = [
    "PreflopDecision",
    "decide_sb_open",
    "decide_bb_defend",
    "decide_sb_vs_threebet",
]
