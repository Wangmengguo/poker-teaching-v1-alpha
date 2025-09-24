from __future__ import annotations

from poker_core.suggest.explanations import load_explanations, render_explanations


def test_render_known_code_with_numbers():
    # Ensure templates load (fallback to zh)
    mapping = load_explanations("zh")
    assert "PF_DEFEND_PRICE_OK" in mapping

    rationale = [
        {
            "code": "PF_DEFEND_PRICE_OK",
            "data": {"pot_odds": 0.3333, "thr": 0.42, "bucket": "small"},
        }
    ]
    out = render_explanations(rationale, meta=None, extras=None)
    assert out and isinstance(out[0], str)
    # Rounded to two decimals via template
    assert "0.33" in out[0]
    assert "0.42" in out[0]
    assert "small" in out[0]


def test_render_unknown_code_falls_back_to_msg():
    rationale = [
        {"code": "UNKNOWN_CODE", "msg": "fallback message"},
    ]
    out = render_explanations(rationale, meta=None, extras=None)
    assert out == ["fallback message"]
