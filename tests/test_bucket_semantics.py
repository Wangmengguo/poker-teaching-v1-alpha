import pytest

from tools import build_buckets


@pytest.fixture(scope="module")
def bucket_configs():
    return build_buckets.generate_bucket_configs(seed=42)


def _assert_label(street, hole, board, expected_label, configs):
    bucket_id, label = build_buckets.assign_bucket(
        street,
        hole_cards=hole,
        board_cards=board,
        configs=configs,
    )
    assert label == expected_label
    assert bucket_id == configs[street]["labels"].index(expected_label)


def test_flop_turn_8bucket_rules_examples(bucket_configs):
    flop_cases = [
        ("value_two_pair_plus", ["Kc", "8c"], ["Kh", "8s", "4d"]),
        ("value_two_pair_plus", ["Ah", "Kh"], ["Qh", "Th", "2h"]),
        ("value_two_pair_plus", ["9c", "8d"], ["Jh", "Td", "Qs"]),
        ("value_two_pair_plus", ["Ah", "5d"], ["2c", "3s", "4h"]),
        ("overpair_or_tptk", ["As", "Kd"], ["Ah", "7s", "2d"]),
        ("top_pair_weak_or_second", ["Kh", "9d"], ["Kc", "8s", "4d"]),
        ("middle_pair_or_third_minus", ["4h", "6d"], ["Kc", "8s", "4d"]),
        ("strong_draw", ["7c", "6c"], ["9c", "8d", "2s"]),
        ("weak_draw", ["5h", "4h"], ["8c", "7d", "2s"]),
        ("overcards_no_bdfd", ["Kh", "Qd"], ["9c", "4d", "2s"]),
        ("air", ["7h", "3d"], ["Kc", "8s", "2d"]),
    ]
    for expected, hole, board in flop_cases:
        _assert_label("flop", hole, board, expected, bucket_configs)

    # 优先级：同时满足成手与强听，应归类成手
    _assert_label(
        "flop",
        ["As", "Ks"],
        ["Ah", "7s", "2s"],
        "overpair_or_tptk",
        bucket_configs,
    )

    turn_cases = [
        ("value_two_pair_plus", ["Qh", "Qs"], ["Qd", "9c", "2s", "7h"]),
        ("value_two_pair_plus", ["Ah", "4h"], ["Qh", "Th", "2h", "9d"]),
        ("value_two_pair_plus", ["Kc", "2d"], ["Jh", "Td", "Qs", "9c"]),
        ("value_two_pair_plus", ["Ah", "7d"], ["Qh", "Th", "6h", "2h", "9h"]),
        ("overpair_or_tptk", ["As", "Kd"], ["Ah", "7s", "2d", "8c"]),
        ("top_pair_weak_or_second", ["Kh", "9d"], ["Kc", "8s", "4d", "2c"]),
        ("middle_pair_or_third_minus", ["4h", "6d"], ["Qh", "Td", "4s", "2c"]),
        ("strong_draw", ["7c", "6c"], ["9c", "8c", "2d", "Kh"]),
        ("weak_draw", ["Jh", "8h"], ["Qd", "Td", "4s", "2c"]),
        ("overcards_no_bdfd", ["Kh", "Qd"], ["9c", "4d", "2s", "7h"]),
        ("air", ["4h", "3d"], ["Kc", "8s", "2d", "Jh"]),
    ]
    for expected, hole, board in turn_cases:
        _assert_label("turn", hole, board, expected, bucket_configs)


def test_flush_on_board_requires_hero_participation(bucket_configs):
    _, label = build_buckets.assign_bucket(
        "turn",
        ["As", "Kd"],
        ["Qh", "Th", "6h", "2h", "9h"],
        configs=bucket_configs,
    )
    assert label == "weak_draw"

    _assert_label(
        "turn",
        ["Ah", "7d"],
        ["Qh", "Th", "6h", "2h", "9h"],
        "value_two_pair_plus",
        bucket_configs,
    )


def test_straight_on_board_requires_hero_participation(bucket_configs):
    _, label = build_buckets.assign_bucket(
        "turn",
        ["As", "2d"],
        ["Jh", "Th", "Qs", "9c", "8d"],
        configs=bucket_configs,
    )
    assert label == "weak_draw"

    _assert_label(
        "turn",
        ["Kc", "2d"],
        ["Jh", "Th", "Qs", "9c", "8d"],
        "value_two_pair_plus",
        bucket_configs,
    )


def test_preflop_6bucket_equiv_classes(bucket_configs):
    preflop_cases = [
        ("premium_pair", ["As", "Ah"]),
        ("strong_broadway", ["As", "Kd"]),
        ("suited_ace", ["Ad", "5d"]),
        ("medium_pair", ["8c", "8d"]),
        ("suited_connectors", ["9s", "8s"]),
        ("junk", ["7h", "2d"]),
    ]
    for expected, hole in preflop_cases:
        _assert_label("preflop", hole, [], expected, bucket_configs)

    # 等价类稳定性：同种子重复计算得到同一 bucket
    bucket_ids = [
        build_buckets.assign_bucket("preflop", hole, [], configs=bucket_configs)[0]
        for _, hole in preflop_cases
    ]
    again = [
        build_buckets.assign_bucket("preflop", hole, [], configs=bucket_configs)[0]
        for _, hole in preflop_cases
    ]
    assert bucket_ids == again
