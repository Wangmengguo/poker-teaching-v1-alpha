from __future__ import annotations

import os
from typing import Any

from .config_loader import load_json_cached
from .decision import Decision
from .decision import SizeSpec
from .types import Observation
from .utils import derive_facing_size_tag_extended
from .utils import find_action
from .utils import stable_weighted_choice


def _load_thresholds() -> dict[str, Any]:
    # Allow override by environment
    override = os.getenv("SUGGEST_DEFENSE_FILE")
    if override:
        try:
            import json

            with open(override, encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            pass
    data, _ = load_json_cached("defense_thresholds.json", ttl_seconds=30)
    return data or {}


def _river_tier(obs: Observation) -> str:
    try:
        from .river_semantics import analyze_river_context

        ctx = analyze_river_context(obs)
        tier = str((ctx or {}).get("tier") or "unknown")
        return tier
    except Exception:
        return "unknown"


def _get_node_cfg(
    thr: dict[str, Any], street: str, obs: Observation, fine: str, base: str
) -> tuple[dict[str, Any] | None, str]:
    # Category selection: river uses value tiers; others use 6-bucket hand_class
    cfg = thr.get(street, {}) if isinstance(thr, dict) else {}
    cat = None
    cat_key = ""
    if street == "river":
        cat = cfg.get(_river_tier(obs))
        cat_key = _river_tier(obs)
    else:
        cat = cfg.get(str(getattr(obs, "hand_class", "")))
        cat_key = str(getattr(obs, "hand_class", ""))
    if not isinstance(cat, dict):
        return None, cat_key
    # Facing selection: prefer fine → base → legacy large → any/defaults
    facing = None
    for k in (fine, base, "two_third+", "any"):
        v = cat.get(k) if isinstance(cat, dict) else None
        if isinstance(v, dict):
            facing = v
            break
    if facing is None:
        # try nested structure {"facing": {...}}
        inner = cat.get("facing") if isinstance(cat, dict) else None
        if isinstance(inner, dict):
            for k in (fine, base, "two_third+", "any"):
                v = inner.get(k)
                if isinstance(v, dict):
                    facing = v
                    break
    return facing, cat_key


def decide_defense(obs: Observation, acts: list, *, enable_mix: bool | None = None):
    """Return (Decision, meta, rationale) or None when not applicable.

    Strategy:
      - Use defense_thresholds to determine action based on pot_odds windows.
      - Priority: raise (when configured and legal) > call (<= call_le) > mix (call in grey window) > fold.
    """
    try:
        to_call = int(getattr(obs, "to_call", 0) or 0)
        pot_now = int(getattr(obs, "pot_now", getattr(obs, "pot", 0)) or 0)
    except Exception:
        to_call = 0
        pot_now = 0
    if to_call <= 0 or pot_now <= 0:
        return None

    base, fine, pot_odds = derive_facing_size_tag_extended(to_call, pot_now)
    street = str(getattr(obs, "street", "")).lower() or "flop"
    thr = _load_thresholds()

    node_cfg, cat_key = _get_node_cfg(thr, street, obs, fine, base)
    if not isinstance(node_cfg, dict):
        return None

    plan = node_cfg.get("plan") if isinstance(node_cfg, dict) else None
    # 1) Raise path (value/thin raise guidance)
    raise_to = node_cfg.get("raise_to")
    raise_call_le = node_cfg.get("raise_call_le", node_cfg.get("call_le", None))
    if raise_to and find_action(list(acts or []), "raise"):
        if raise_call_le is None or float(pot_odds) <= float(raise_call_le):
            dec = Decision(
                action="raise", sizing=SizeSpec.tag(str(raise_to)), meta={"size_tag": str(raise_to)}
            )
            meta = {"size_tag": str(raise_to), "plan": plan, "source": "defense"}
            return dec, meta, []

    # 2) Direct call threshold
    call_le = node_cfg.get("call_le")
    if (
        call_le is not None
        and find_action(list(acts or []), "call")
        and float(pot_odds) <= float(call_le)
    ):
        dec = Decision(action="call", meta={})
        meta = {"plan": plan, "source": "defense"}
        return dec, meta, []

    # 3) Grey window mixing (deterministic)
    mix_to = node_cfg.get("mix_to")
    mix_freq = node_cfg.get("mix_freq", 0.35)
    if (
        call_le is not None
        and mix_to is not None
        and float(call_le) < float(pot_odds) <= float(mix_to)
        and find_action(list(acts or []), "call")
    ):
        flag_mix = enable_mix
        if flag_mix is None:
            flag_mix = (os.getenv("SUGGEST_MIXING") or "on").strip().lower() == "on"
        if flag_mix:
            # Stable seed per hand+node
            try:
                from .node_key import node_key_from_observation as _nk

                node_key = _nk(obs) or ""
            except Exception:
                node_key = ""
            seed = f"defense:{getattr(obs, 'hand_id', '')}:{street}:{fine}:{round(pot_odds,3)}:{node_key}"
            idx = stable_weighted_choice(seed, [1.0 - float(mix_freq), float(mix_freq)])
            if idx == 1:
                dec = Decision(action="call", meta={})
                meta = {
                    "plan": plan or "灰区混频防守",
                    "source": "defense",
                    "frequency": float(mix_freq),
                }
                return dec, meta, []

    # 4) Fold guidance
    fold_gt = node_cfg.get("fold_gt")
    if (
        fold_gt is not None
        and float(pot_odds) > float(fold_gt)
        and find_action(list(acts or []), "fold")
    ):
        dec = Decision(action="fold", meta={})
        meta = {"plan": plan, "source": "defense"}
        return dec, meta, []

    # 5) Last resort heuristics: allow conservative call vs small sizes, else fold
    if base in {"small", "third"} and find_action(list(acts or []), "call"):
        dec = Decision(action="call", meta={})
        meta = {"plan": plan or "小尺吋：价格可接受，保守跟注", "source": "defense"}
        return dec, meta, []

    if find_action(list(acts or []), "fold"):
        dec = Decision(action="fold", meta={})
        meta = {"plan": plan or "价格过差，弃牌保守", "source": "defense"}
        return dec, meta, []

    # If nothing matched, do nothing
    return None


__all__ = ["decide_defense"]
