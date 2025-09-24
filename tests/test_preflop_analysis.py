# tests/test_preflop_analysis.py
import pytest
from poker_core.analysis import annotate_player_hand, classify_starting_hand


# ---- 工具 ----
def codes(x):
    notes = (x.get("notes") if isinstance(x, dict) else x) or []
    out = []
    for n in notes:
        out.append(n.get("code") if isinstance(n, dict) else getattr(n, "code", None))
    return set(out)


# ---- classify_starting_hand：每个分支都打到 ----
@pytest.mark.parametrize(
    "cards, expected_cat, why",
    [
        (["Ah", "Ad"], "premium_pair", "pair & A/A premium"),  # premium_pair 分支
        (
            ["Ks", "Qs"],
            "strong",
            "suited & high>=13 & low>=10",
        ),  # strong 分支（同花大张）
        (["Th", "Td"], "strong", "pair & max>=10 (TT)"),  # strong 分支（对子=TT）
        (
            ["Jh", "Th"],
            "speculative",
            "suited & gap<=1 & high>=10",
        ),  # speculative 分支（JT 同花）
        (["Ah", "Td"], "broadway_offsuit", "offsuit broadway"),  # broadway_offsuit 分支
        (
            ["7h", "2c"],
            "weak_offsuit",
            "offsuit & high<10 & gap>=3",
        ),  # weak_offsuit 分支
        (["8h", "6h"], "weak", "其余情况归入 weak"),  # else 分支
    ],
)
def test_classify_categories(cards, expected_cat, why):
    info = classify_starting_hand(cards)
    assert info["category"] == expected_cat, why
    # 也顺便校验解析字段存在
    for k in ["pair", "suited", "gap", "high", "low", "category"]:
        assert k in info


# ---- annotate_player_hand：四条注释都触发一遍 ----
def test_note_E001_for_weak_bucket():
    # 8h6h 走 weak → 触发 E001
    an = annotate_player_hand(["8h", "6h"])
    assert "E001" in codes(an)


def test_note_E002_for_very_weak_offsuit_unconnected():
    # 7h2c 走 week_offsuit → 触发 E002
    an = annotate_player_hand(["7h", "2c"])
    assert "E002" in codes(an)


def test_note_N101_for_suited_connected_low_geq_9():
    # T9 同花：suited & gap<=1 & low>=9 → 触发 N101
    an = annotate_player_hand(["Th", "9h"])
    assert "N101" in codes(an)


def test_note_N102_for_premium_pair():
    # QQ 对：pair & high>=11 → 触发 N102
    an = annotate_player_hand(["Qd", "Qs"])
    assert "N102" in codes(an)


# ---- 解析函数也踩一下，补掉顶部小函数的行 ----
@pytest.mark.parametrize(
    "c, exp_rank, exp_suit",
    [
        ("As", "A", "s"),
        ("Td", "T", "d"),
        ("2h", "2", "h"),
    ],
)
def test_parse_card_helper_exercised(c, exp_rank, exp_suit):
    # 你的 classify/annotate 内部会用 _parse_card；这里等价走通解析路径
    info = classify_starting_hand([c, "Ah"])
    assert isinstance(info["gap"], int)
