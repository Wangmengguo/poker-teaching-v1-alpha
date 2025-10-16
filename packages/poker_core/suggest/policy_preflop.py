"""Preflop helper modules extracted from policy_preflop_v1."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache

from poker_core.domain.actions import LegalAction
from poker_core.suggest.codes import SCodes
from poker_core.suggest.codes import mk_rationale as R
from poker_core.suggest.context import SuggestContext
from poker_core.suggest.decision import Decision
from poker_core.suggest.decision import SizeSpec
from poker_core.suggest.preflop_tables import bucket_facing_size
from poker_core.suggest.types import Observation
from poker_core.suggest.types import PolicyConfig
from poker_core.suggest.utils import find_action
from poker_core.suggest.utils import pick_betlike_action
from poker_core.suggest.utils import stable_weighted_choice

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
    "decide_preflop_exploit_firstin_allin",
    "decide_sb_open",
    "decide_bb_defend",
    "decide_sb_vs_threebet",
]


# -------- Preflop vs Shove (HU) — dedicated defense (v1) --------


@lru_cache(maxsize=16)
def _load_vs_shove_config(config_dir: str | None = None, profile_tag: str | None = None) -> dict:
    """Load HU preflop vs-shove defense table from config dir.

    Structure example:
    {
      "le12": {"call": ["77","88","AJs",...], "mix": ["AJo","KQs"]},
      "13to20": {"call": [...], "mix": [...]},
      "gt20": {"call": [...], "mix": [...]}
    }
    """
    # feature gate (default on)
    if (os.getenv("SUGGEST_PREFLOP_DEFEND_SHOVE") or "1").strip() == "0":
        return {}

    root = (
        config_dir
        or os.getenv("SUGGEST_CONFIG_DIR")
        or os.path.join(
            "packages",
            "poker_core",
            "suggest",
            "config",
        )
    )
    # Support exploit profile override (manual toggle for simple opponent archetypes)
    exploit = (profile_tag or os.getenv("SUGGEST_EXPLOIT_PROFILE") or "").strip().lower()
    prefer_exploit = exploit in {"vs_allin", "always_allin", "allin"}
    primary = (
        os.path.join(root, "preflop_vs_shove_HU_exploit.json")
        if prefer_exploit
        else os.path.join(root, "preflop_vs_shove_HU.json")
    )
    fallback = os.path.join(root, "preflop_vs_shove_HU.json")

    def _read(p: str) -> dict:
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    data = _read(primary)
    if not data and prefer_exploit:
        # Fallback to default when exploit file is absent or invalid
        data = _read(fallback)
    return data


def _mixing_enabled() -> bool:
    # Default to on for robustness
    return (os.getenv("SUGGEST_MIXING") or "on").strip().lower() == "on"


def _band_by_to_call_bb(to_call_bb: float) -> str:
    if to_call_bb <= 12.0:
        return "le12"
    if to_call_bb <= 20.0:
        return "13to20"
    return "gt20"


def decide_preflop_vs_shove(
    obs: Observation, ctx: SuggestContext, cfg: PolicyConfig
) -> PreflopDecision | None:
    """Defend vs preflop all-in (fold/call only state).

    - Uses config table to determine forced calls and mixed calls.
    - Mixed calls use deterministic hashing when SUGGEST_MIXING=on.
    """
    if obs.street != "preflop":
        return None

    names = {a.action for a in (obs.acts or [])}
    try:
        to_call_bb = float(obs.to_call) / float(obs.bb or 1)
    except Exception:
        to_call_bb = 0.0
    # Robust detection: either (a) strict call/fold-only node, or (b) to_call is large
    # enough to imply facing an all-in (some engines still list a dummy 'raise').
    # Threshold is configurable; default 8bb to catch typical shove sizes.
    try:
        thr = float(os.getenv("SUGGEST_SHOVE_DETECT_TO_CALL_BB") or 8.0)
    except Exception:
        thr = 8.0
    pure_call_fold = "call" in names and "fold" in names and names <= {"call", "fold"}
    large_to_call_like_shove = "call" in names and to_call_bb >= thr
    if not (pure_call_fold or large_to_call_like_shove):
        return None  # not a shove-facing node
    band = _band_by_to_call_bb(to_call_bb)

    cfg_tab = (
        _load_vs_shove_config(
            os.getenv("SUGGEST_CONFIG_DIR"),
            profile_tag=(os.getenv("SUGGEST_EXPLOIT_PROFILE") or ""),
        )
        or {}
    )
    node = cfg_tab.get(band, {}) if isinstance(cfg_tab, dict) else {}
    call_set = set(node.get("call", []) or [])
    mix_set = set(node.get("mix", []) or [])
    mix_map = node.get("mix_map", {}) if isinstance(node, dict) else {}

    combo = str(obs.combo or "")
    rationale: list[dict] = []

    if combo in call_set and find_action(obs.acts, "call"):
        rationale.append(
            R(
                SCodes.PF_DEFEND_PRICE_OK,
                data={"to_call_bb": round(to_call_bb, 2), "band": band, "src": "vs_shove"},
            )
        )
        decision = Decision(
            action="call", meta={"vs_shove_band": band, "to_call_bb": round(to_call_bb, 2)}
        )
        return PreflopDecision(decision, rationale, meta={})

    if combo in mix_set and find_action(obs.acts, "call"):
        # Base frequencies by band (le12 wider defend), allow combo override via mix_map
        base = {"le12": 0.5, "13to20": 0.4, "gt20": 0.33}.get(band, 0.4)
        try:
            v = mix_map.get(combo)
            if isinstance(v, (int, float)):
                base = float(v)
        except Exception:
            pass
        if _mixing_enabled():
            seed_key = f"pf_vs_shove:{obs.hand_id}:{combo}:{band}:{round(to_call_bb,2)}"
            idx = stable_weighted_choice(seed_key, [1.0 - base, base])
            if idx == 1:
                rationale.append(
                    R(
                        SCodes.PF_DEFEND_PRICE_OK,
                        data={"to_call_bb": round(to_call_bb, 2), "band": band, "mix": base},
                    )
                )
                decision = Decision(
                    action="call",
                    meta={
                        "vs_shove_band": band,
                        "to_call_bb": round(to_call_bb, 2),
                        "frequency": base,
                    },
                )
                return PreflopDecision(decision, rationale, meta={})
        # mixing off → fall through to default handling (likely fold)
    return None


# -------- Exploit: first-in all-in vs always-all-in opponent --------


def _exploit_enabled() -> bool:
    tag = (os.getenv("SUGGEST_EXPLOIT_PROFILE") or "").strip().lower()
    return tag in {"vs_allin", "always_allin", "allin"}


def _band_by_eff_firstin(obs: Observation) -> str:
    try:
        # for first-in we approximate band by spr bucket when available; fall back to to_call
        if getattr(obs, "spr_bucket", None) in {"low", "mid", "high"}:
            m = {"low": "le12", "mid": "13to20", "high": "gt20"}
            return m.get(obs.spr_bucket, "gt20")
        to_call_bb = float(obs.to_call or 0) / float(obs.bb or 1)
        return _band_by_to_call_bb(to_call_bb)
    except Exception:
        return "gt20"


def _combo_is_pair(combo: str) -> bool:
    if not combo:
        return False
    return combo in {"22", "33", "44", "55", "66", "77", "88", "99", "TT", "JJ", "QQ", "KK", "AA"}


def _exploit_jam_ok(combo: str, band: str) -> bool:
    if not combo or len(combo) < 2:
        return False
    c = combo.strip()
    # Any pair is good (equity vs random > ~50%)
    if _combo_is_pair(c):
        return True
    r1 = c[0]
    r2 = c[1]
    suited = c.endswith("s")
    offsuit = c.endswith("o")
    # Ax: jam any Ace
    if r1 == "A":
        return True
    # Broadways and strong Kx/Qx
    strong_k = {"KQ", "KJ", "KT", "K9"}
    strong_q = {"QJ", "QT"}
    strong_j = {"JT"}
    strong_t = {"T9"}
    heads = r1 + r2
    if heads in strong_k:
        return True if offsuit or suited else True
    if heads in strong_q:
        return True if offsuit or suited else True
    if heads in strong_j:
        return suited  # prefer suited for JT
    if heads in strong_t:
        return suited  # T9s
    # Slightly tighter in ultra short band? keep as above — conservative already gated by heads
    return False


def decide_preflop_exploit_firstin_allin(
    obs: Observation, ctx: SuggestContext, cfg: PolicyConfig
) -> PreflopDecision | None:
    """When acting first preflop and exploit profile is on, jam first with high-equity hands.

    Idea: vs an opponent who (a) jams on their turns and (b) will call our jam,
    first-in jam with hands whose equity vs random > ~to_call/(to_call+opp_invest+pot) ≈ 0.5 at deep stacks.
    This flips the EV and prevents them from profiting solely via fold equity.
    """
    if not _exploit_enabled():
        return None
    if obs.street != "preflop" or not bool(obs.first_to_act):
        return None
    # Allow SB blind completion scenario as first-in
    try:
        to_call = float(obs.to_call or 0)
        bb = float(obs.bb or 0)
    except Exception:
        to_call = 0.0
        bb = 0.0
    if to_call > max(bb, 0.0):
        return None
    if not find_action(obs.acts, "allin"):
        return None

    combo = obs.combo or ""
    band = _band_by_eff_firstin(obs)
    if _exploit_jam_ok(combo, band):
        decision = Decision(
            action="allin",
            meta={
                "vs": "always_allin",
                "plan": "对手倾向全下：先手用高权益牌直接全下以反制。",
                "band": band,
            },
        )
        rationale = [
            R(SCodes.PF_DEFEND_PRICE_OK, data={"src": "exploit_firstin_allin", "band": band})
        ]
        return PreflopDecision(decision=decision, rationale=rationale, meta={})
    return None
