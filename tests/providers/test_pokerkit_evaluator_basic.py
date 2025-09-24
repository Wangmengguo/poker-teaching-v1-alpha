import pytest
from poker_core.providers.interfaces import EvaluationError
from poker_core.providers.pokerkit_adapter import PokerKitEvaluator

E = PokerKitEvaluator()


def test_eval_consistency_order_invariant():
    hole = ["As", "Kd"]
    board = ["Qh", "Js", "Ts", "9c", "8d"]
    r1 = E.evaluate7(hole, board)
    r2 = E.evaluate7(["Kd", "As"], ["8d", "9c", "Ts", "Js", "Qh"])  # 打乱顺序
    assert r1.strength == r2.strength
    assert set(r1.best5) == set(r2.best5)


def test_eval_reject_non_7_cards():
    with pytest.raises(ValueError):
        E.evaluate7(["As"], ["Qh", "Js", "Ts", "9c", "8d"])  # 1+5


def test_eval_reject_duplicate_cards():
    with pytest.raises(EvaluationError):
        E.evaluate7(["As", "As"], ["Qh", "Js", "Ts", "9c", "8d"])  # 重复


def test_eval_accept_10_variants():
    r = E.evaluate7(["10s", "Ah"], ["Kh", "Qh", "Jh", "Th", "9h"])
    r2 = E.evaluate7(["Ts", "Ah"], ["Kh", "Qh", "Jh", "Th", "9h"])
    assert r.strength == r2.strength


def test_basic_hand_rankings():
    """测试基本牌型排名：同花顺 > 四条 > 葫芦 > 同花"""
    # 同花顺
    sf = E.evaluate7(["9s", "8s"], ["7s", "6s", "5s", "Ac", "Kd"])
    # 四条
    quads = E.evaluate7(["As", "Ad"], ["Ah", "Ac", "Ks", "Qd", "Jh"])
    # 葫芦
    full_house = E.evaluate7(["Ks", "Kd"], ["Kh", "Ac", "As", "Qd", "Jh"])
    # 同花
    flush = E.evaluate7(["As", "Qs"], ["Js", "9s", "7s", "Kd", "2h"])

    assert sf.strength > quads.strength
    assert quads.strength > full_house.strength
    assert full_house.strength > flush.strength


def test_tie_scenarios():
    """测试各种平局情况"""
    # 公共牌造成的平局（皇家同花顺）
    r1 = E.evaluate7(["2c", "3d"], ["As", "Ks", "Qs", "Js", "Ts"])
    r2 = E.evaluate7(["4h", "5h"], ["As", "Ks", "Qs", "Js", "Ts"])
    assert r1.strength == r2.strength

    # 相同牌型平局（都是对子A）
    r3 = E.evaluate7(["As", "Ah"], ["Kd", "Qc", "Js", "9h", "7d"])
    r4 = E.evaluate7(["Ac", "Ad"], ["Kd", "Qc", "Js", "9h", "7d"])
    assert r3.strength == r4.strength


def test_kicker_comparison():
    """测试踢脚牌对比"""
    # 都是对子K，但踢脚牌不同
    r1 = E.evaluate7(["Ks", "Kh"], ["As", "Qd", "Jc", "9h", "7d"])  # 对K + A,Q,J踢脚
    r2 = E.evaluate7(["Kd", "Kc"], ["As", "Qh", "Tc", "9s", "6c"])  # 对K + A,Q,T踢脚（J > T）
    assert r1.strength > r2.strength  # J > T


def test_high_card_comparison():
    """测试高牌对比"""
    # 都是高牌，测试踢脚对比
    r1 = E.evaluate7(["As", "Kh"], ["Qd", "Jc", "9h", "7d", "5s"])  # A,K,Q,J,9
    r2 = E.evaluate7(["Ad", "Qc"], ["Jh", "Ts", "9s", "7c", "5h"])  # A,Q,J,T,9 (K vs Q)
    assert r1.strength > r2.strength


def test_wheel_straight():
    """测试A-2-3-4-5顺子（轮子）"""
    wheel = E.evaluate7(["As", "2h"], ["3d", "4c", "5s", "Kh", "Qd"])
    high_straight = E.evaluate7(["9s", "Th"], ["Jd", "Qc", "Ks", "Ah", "2d"])
    assert high_straight.strength > wheel.strength  # 高顺子应该击败轮子


def test_best5_short_codes_from_attrs():
    hole = ["As", "Ks"]
    board = ["Qs", "Js", "Ts", "9c", "8d"]
    r = E.evaluate7(hole, board)
    assert all(len(x) == 2 and x[0] in "23456789TJQKA" and x[1] in "cdhs" for x in r.best5)


def test_rank_10_normalized_to_T():
    hole = ["10s", "Ah"]
    board = ["Kh", "Qh", "Jh", "Th", "9h"]
    r = E.evaluate7(hole, board)
    assert any(x.startswith("T") for x in r.best5)
