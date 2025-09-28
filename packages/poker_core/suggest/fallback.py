"""Conservative fallback heuristics when policies cannot provide a node."""

from __future__ import annotations

from typing import Any

from poker_core.domain.actions import LegalAction

from .codes import SCodes
from .codes import mk_rationale as R
from .types import Observation
from .utils import find_action


def _safe_to_call(obs: Observation, call_action: LegalAction | None) -> int:
    """Derive the integer cost to call from observation + legal action."""

    try:
        if getattr(obs, "to_call", None) is not None:
            return max(0, int(obs.to_call or 0))  # type: ignore[arg-type]
    except Exception:
        pass
    if call_action and call_action.to_call is not None:
        try:
            return max(0, int(call_action.to_call))
        except Exception:
            return 0
    return 0


def _pot_odds(to_call: int, pot_now: int) -> float:
    denom = pot_now + max(0, to_call)
    return float(to_call) / float(denom) if denom > 0 else 1.0


def choose_conservative_line(
    obs: Observation, acts: list[LegalAction]
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Fallback decision: prefer passive/legal options, avoid aggression."""

    acts = list(acts or [])
    if not acts:
        raise ValueError("No legal actions available for fallback")

    rationale = [R(SCodes.CFG_FALLBACK_USED)]
    meta: dict[str, Any] = {
        "policy_source": "fallback",
        "fallback_used": True,
    }

    check = find_action(acts, "check")
    call = find_action(acts, "call")
    fold = find_action(acts, "fold")

    bb = 0
    try:
        bb = max(0, int(getattr(obs, "bb", 0) or 0))
    except Exception:
        bb = 0

    pot_now = 0
    try:
        pot_now = int(getattr(obs, "pot_now", getattr(obs, "pot", 0)) or 0)
    except Exception:
        pot_now = 0

    to_call = _safe_to_call(obs, call)

    if to_call <= 0:
        if check:
            return {"action": "check"}, meta, rationale
        if call:
            return {"action": "call"}, meta, rationale
        if fold:
            return {"action": "fold"}, meta, rationale
        for name in ("call", "check", "fold"):
            act = find_action(acts, name)
            if act:
                return {"action": act.action}, meta, rationale
        non_aggressive = next(
            (a for a in acts if a.action not in {"bet", "raise", "allin"}),
            None,
        )
        if non_aggressive:
            return {"action": non_aggressive.action}, meta, rationale
        # Last resort when only aggressive options remain.
        return {"action": acts[0].action}, meta, rationale

    pot_odds_val = _pot_odds(to_call, pot_now)
    meta.update(
        {
            "fallback_to_call": int(to_call),
            "fallback_pot_odds": round(pot_odds_val, 4),
        }
    )

    # Cheap calls (≤1bb) are acceptable for blinds completion / pot control.
    if call and to_call <= max(bb, 1):
        return {"action": "call"}, meta, rationale

    # Acceptable odds (≤25%) still warrant a call; otherwise prefer folding.
    if call and pot_odds_val <= 0.25:
        return {"action": "call"}, meta, rationale

    if fold:
        return {"action": "fold"}, meta, rationale

    if check and to_call <= 0:
        return {"action": "check"}, meta, rationale

    if call:
        return {"action": "call"}, meta, rationale

    for name in ("check", "fold"):
        act = find_action(acts, name)
        if act:
            return {"action": act.action}, meta, rationale

    non_aggressive = next(
        (a for a in acts if a.action not in {"bet", "raise", "allin"}),
        None,
    )
    if non_aggressive:
        return {"action": non_aggressive.action}, meta, rationale

    # As a final fallback, return the first legal action even if aggressive.
    return {"action": acts[0].action}, meta, rationale


__all__ = ["choose_conservative_line"]
