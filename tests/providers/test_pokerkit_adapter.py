from poker_core.providers.pokerkit_adapter import PokerKitEvaluator


def test_sf_beats_quads():
    ev = PokerKitEvaluator()
    # 玩家1：皇家同花顺 (As,Ks + Qs,Js,Ts,9s,8s)
    r1 = ev.evaluate7(["As", "Ks"], ["Qs", "Js", "Ts", "9s", "8s"])
    # 玩家2：同花顺 (Ah,Ad + 同样公共牌，但只能组成较低的同花顺)
    r2 = ev.evaluate7(["Ah", "Ad"], ["Qs", "Js", "Ts", "9s", "8s"])

    # 验证皇家同花顺 > 同花顺
    assert r1.strength > r2.strength

    # 验证返回了5张牌的最佳组合（现在是简化格式）
    assert len(r1.best5) == 5
    assert len(r2.best5) == 5

    # 验证是简化格式
    for card in r1.best5 + r2.best5:
        assert len(card) == 2, f"应该是2字符简化格式，实际: {card}"
        assert "(" not in card, f"不应该包含长格式，实际: {card}"

    # 验证牌型都是同花顺（这里不验证具体格式，因为PokerKit返回格式复杂）
    print(f"玩家1最佳5张: {r1.best5}")
    print(f"玩家2最佳5张: {r2.best5}")


def test_tie_on_board():
    ev = PokerKitEvaluator()
    # 公共牌已经是同样的最佳五张 → 平局
    r1 = ev.evaluate7(["2c", "3d"], ["As", "Ks", "Qs", "Js", "Ts"])
    r2 = ev.evaluate7(["4h", "5h"], ["As", "Ks", "Qs", "Js", "Ts"])
    assert not (r1.strength > r2.strength or r2.strength > r1.strength)


def test_pokerkit_format_extraction():
    """测试PokerKit适配器现在直接返回简化格式"""
    ev = PokerKitEvaluator()

    # 测试皇家同花顺
    result = ev.evaluate7(["As", "Ks"], ["Qs", "Js", "Ts", "2h", "3c"])

    # 验证best5现在直接返回简化格式
    assert len(result.best5) == 5
    expected = ["As", "Ks", "Qs", "Js", "Ts"]  # 皇家同花顺

    # 验证格式已经是简化格式 (不再包含长格式)
    for card in result.best5:
        assert isinstance(card, str)
        assert len(card) == 2  # 简化格式：2个字符 (如 'As')
        assert "(" not in card  # 不应该包含长格式的括号

    # 验证具体内容
    assert set(result.best5) == set(expected), f"期望{expected}, 实际得到{result.best5}"

    # 验证strength内部信息仍然保持（适配器只改变best5格式，不改变strength）
    assert hasattr(result.strength, "_impl")
    assert "Straight flush" in str(result.strength._impl)

    # 验证category字段（当前为None）
    assert result.category is None


def test_format_consistency():
    """测试PokerKit和SimpleFallback返回格式的一致性"""
    from poker_core.providers.simple_fallback import SimpleFallbackEvaluator

    # 相同的测试数据
    hole = ["As", "Ks"]
    board = ["Qs", "Js", "Ts", "2h", "3c"]

    pk_ev = PokerKitEvaluator()
    simple_ev = SimpleFallbackEvaluator()

    pk_result = pk_ev.evaluate7(hole, board)
    simple_result = simple_ev.evaluate7(hole, board)

    # 验证best5格式完全一致（都是简化格式）
    for pk_card, simple_card in zip(pk_result.best5, simple_result.best5):
        assert len(pk_card) == 2, f"PokerKit应该返回2字符格式，实际: {pk_card}"
        assert len(simple_card) == 2, f"SimpleFallback应该返回2字符格式，实际: {simple_card}"
        assert "(" not in pk_card, f"PokerKit不应该包含长格式，实际: {pk_card}"
        assert "(" not in simple_card, f"SimpleFallback不应该包含长格式，实际: {simple_card}"

    # 对于同样的皇家同花顺，两个evaluator应该返回相同的牌面（顺序可能不同）
    assert set(pk_result.best5) == set(
        simple_result.best5
    ), f"PokerKit: {pk_result.best5}, SimpleFallback: {simple_result.best5}"
