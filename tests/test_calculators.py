import pytest


@pytest.mark.parametrize(
    "to_call,pot_now,expected",
    [
        (0, 0, 0.0),
        (0, 100, 0.0),
        (50, 150, 50 / 200),
        (40, 0, 1.0),
        (-10, 120, 0.0),
    ],
)
def test_pot_odds(to_call, pot_now, expected):
    from poker_core.suggest import calculators as calc

    result = calc.pot_odds(to_call, pot_now)
    assert result == pytest.approx(expected, rel=1e-6)


@pytest.mark.parametrize(
    "to_call,pot_now,expected",
    [
        (0, 100, 1.0),
        (50, 150, 1 - (50 / 200)),
        (40, 0, 0.0),
    ],
)
def test_mdf(to_call, pot_now, expected):
    from poker_core.suggest import calculators as calc

    result = calc.mdf(to_call, pot_now)
    assert result == pytest.approx(expected, rel=1e-6)


@pytest.mark.parametrize(
    "bb_mult,bb,expected",
    [
        (2.5, 50, 125),
        (3.0, 100, 300),
        (0.5, 40, 20),
    ],
)
def test_size_from_bb(bb_mult, bb, expected):
    from poker_core.suggest import calculators as calc

    assert calc.size_from_bb(bb_mult, bb) == expected


@pytest.mark.parametrize(
    "size_tag,pot_now,last_bet,bb,expected",
    [
        ("third", 300, 0, 50, 100),
        ("half", 300, 0, 50, 150),
        ("two_third", 300, 0, 50, 200),
        ("pot", 300, 0, 50, 300),
    ],
)
def test_size_from_tag_basic(size_tag, pot_now, last_bet, bb, expected):
    from poker_core.suggest import calculators as calc

    assert calc.size_from_tag(size_tag, pot_now, last_bet, bb) == expected


def test_size_from_tag_rejects_unknown():
    from poker_core.suggest import calculators as calc

    with pytest.raises(ValueError):
        calc.size_from_tag("invalid", 200, 0, 50)


def test_size_from_tag_all_in_clamped_to_positive():
    from poker_core.suggest import calculators as calc

    # even with empty pot the amount should be at least bb
    assert calc.size_from_tag("all_in", 0, 0, 50) >= 50
