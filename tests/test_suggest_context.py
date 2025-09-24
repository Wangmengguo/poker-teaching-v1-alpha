import pytest


def test_suggest_context_loads_config(monkeypatch):
    from poker_core.suggest.context import SuggestContext
    from poker_core.suggest.preflop_tables import get_modes

    ctx = SuggestContext.build()

    modes_snapshot, modes_ver = get_modes()
    assert ctx.modes == modes_snapshot
    assert ctx.versions["modes"] == modes_ver
    assert ctx.profile.strategy_name in {"loose", "medium", "tight"}


@pytest.mark.parametrize("value,expected", [(None, True), ("1", True), ("0", False)])
def test_flop_value_raise_toggle(monkeypatch, value, expected):
    from poker_core.suggest.context import SuggestContext

    if value is None:
        monkeypatch.delenv("SUGGEST_FLOP_VALUE_RAISE", raising=False)
    else:
        monkeypatch.setenv("SUGGEST_FLOP_VALUE_RAISE", value)

    ctx = SuggestContext.build()
    assert ctx.flags.enable_flop_value_raise is expected
