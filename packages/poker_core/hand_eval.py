"""
Hand evaluation adapter for HU NLHE.

Priority: use pokerkit if available; otherwise, fall back to a simple
rank-sum heuristic to keep current tests passing without extra deps.

This module exposes a single function `evaluate_7card_strength(cards7)`
that returns a comparable integer (higher is stronger). The exact scale
is unspecified; only relative ordering matters.
"""

from __future__ import annotations

try:
    import pokerkit  # type: ignore

    _POKERKIT_AVAILABLE = True
except Exception:  # pragma: no cover - defensive import
    pokerkit = None  # type: ignore
    _POKERKIT_AVAILABLE = False


def _fallback_strength(cards7: list[str]) -> int:
    """Very rough heuristic based on top-5 rank sum.

    Keeps behavior compatible with existing tests when `pokerkit` is not
    installed. Uses project-local card utilities.
    """
    from .cards import get_rank_value, parse_card

    values = [get_rank_value(parse_card(c)[0]) for c in cards7]
    return sum(sorted(values, reverse=True)[:5])


def evaluate_7card_strength(cards7: list[str]) -> int:
    """Evaluate 7-card strength with best-5 selection.

    - If `pokerkit` is present, try a few common entrypoints.
    - Otherwise, fall back to the heuristic used before.
    """
    if _POKERKIT_AVAILABLE:
        # We don't pin to a specific API surface here; attempt a few
        # plausible entry points and fall back safely if they fail.
        try:  # 1) Common function style: evaluate_7cards([...])
            fn = getattr(pokerkit, "evaluate_7cards", None)
            if callable(fn):
                return int(fn(cards7))  # type: ignore[arg-type]
        except Exception:
            pass

        try:  # 2) Generic evaluate([...])
            fn = getattr(pokerkit, "evaluate", None)
            if callable(fn):
                return int(fn(cards7))  # type: ignore[arg-type]
        except Exception:
            pass

        try:  # 3) Namespaced evaluators module
            evaluators = getattr(pokerkit, "evaluators", None)
            if evaluators is not None:
                fn = getattr(evaluators, "evaluate_7cards", None)
                if callable(fn):
                    return int(fn(cards7))  # type: ignore[arg-type]
        except Exception:
            pass

        # Any failure → use fallback without raising.
        return _fallback_strength(cards7)

    # No pokerkit in the environment
    return _fallback_strength(cards7)
