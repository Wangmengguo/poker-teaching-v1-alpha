"""CLI tool for generating preflop/flop/turn bucket configurations (6-8-8).

from __future__ import annotations

The module exposes three public helpers used by tests:
- ``generate_bucket_configs``: return deterministic in-memory definitions.
- ``assign_bucket``: classify a given observation into a bucket.
- ``main``: CLI entrypoint compatible with ``python -m tools.build_buckets``.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path

from poker_core.cards import RANK_ORDER, parse_card

_PRE_FLOP_LABELS = [
    "premium_pair",
    "strong_broadway",
    "suited_ace",
    "medium_pair",
    "suited_connectors",
    "junk",
]

_POST_FLOP_LABELS = [
    "value_two_pair_plus",
    "overpair_or_tptk",
    "top_pair_weak_or_second",
    "middle_pair_or_third_minus",
    "strong_draw",
    "weak_draw",
    "overcards_no_bdfd",
    "air",
]

_POST_FLOP_RULES = [
    {
        "label": "value_two_pair_plus",
        "description": "Two pair or better using at least one hole card (includes sets/full house).",
        "conditions": [
            "hero_trips_or_better",
            "hero_pairs_two_distinct_board_ranks",
            "pocket_pair_plus_board_pair",
        ],
    },
    {
        "label": "overpair_or_tptk",
        "description": "Pocket pair higher than top board card or top pair with top kicker (Q+).",
        "conditions": [
            "pocket_pair_above_board",
            "top_pair_top_kicker",
        ],
    },
    {
        "label": "top_pair_weak_or_second",
        "description": "Top pair with weaker kicker, or second pair showdown value.",
        "conditions": [
            "top_pair_sub_top_kicker",
            "second_pair",
        ],
    },
    {
        "label": "middle_pair_or_third_minus",
        "description": "Third pair or pocket pair under the board providing marginal showdown value.",
        "conditions": [
            "third_pair",
            "underpair_using_pocket_pair",
        ],
    },
    {
        "label": "strong_draw",
        "description": "Flush draw or open-ended straight draw (including combo draws).",
        "conditions": [
            "flush_draw",
            "open_ended_straight_draw",
        ],
    },
    {
        "label": "weak_draw",
        "description": "Gutshot straight draw or backdoor flush draw without stronger made hand.",
        "conditions": [
            "gutshot",
            "backdoor_flush_draw",
        ],
    },
    {
        "label": "overcards_no_bdfd",
        "description": "Two overcards to the board with no backdoor flush draw available.",
        "conditions": [
            "two_overcards",
            "no_backdoor_flush_draw",
        ],
    },
    {
        "label": "air",
        "description": "Hands that do not meet any made hand or draw criteria above.",
        "conditions": ["fallback"],
    },
]

_PRE_FLOP_RULES = [
    {
        "label": "premium_pair",
        "description": "Pocket pair QQ+ (premium) or better.",
        "conditions": ["pocket_pair_rank_ge_Q"],
    },
    {
        "label": "strong_broadway",
        "description": "Two broadway cards (A/K/Q/J/T) that are not a pocket pair.",
        "conditions": ["both_cards_broadway"],
    },
    {
        "label": "suited_ace",
        "description": "Suited ace that is not already classified as premium/strong broadway.",
        "conditions": ["ace_suited"],
    },
    {
        "label": "medium_pair",
        "description": "Pocket pair TT or below (6 buckets default treat as medium).",
        "conditions": ["pocket_pair_rank_lt_Q"],
    },
    {
        "label": "suited_connectors",
        "description": "Suited consecutive ranks 65s–T9s (connectors).",
        "conditions": ["suited_consecutive"],
    },
    {
        "label": "junk",
        "description": "Hands that do not match any stronger preflop bucket.",
        "conditions": ["fallback"],
    },
]


def _normalize_cards(cards: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for card in cards or []:
        c = card.strip()
        if len(c) != 2:
            raise ValueError(f"Invalid card representation: {card}")
        rank = c[0].upper()
        suit = c[1].lower()
        normalized.append(rank + suit)
    return normalized


def _rank_values(ranks: Iterable[str]) -> list[int]:
    return [RANK_ORDER.get(r, 0) for r in ranks]


def _sorted_board_ranks(board: list[str]) -> list[str]:
    unique = []
    seen = set()
    for r in sorted(board, key=lambda x: RANK_ORDER.get(x, 0), reverse=True):
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return unique


def _has_two_pair_plus(hole: list[str], board: list[str]) -> bool:
    hero_counts = Counter(hole)
    board_counts = Counter(board)
    combined_counts = Counter(hole + board)

    # Trips or better where hero contributes at least one card.
    for rank, total in combined_counts.items():
        if total >= 3 and hero_counts.get(rank, 0) > 0:
            return True

    # Hero pairs two distinct board ranks (e.g., Kx + 8x on K84).
    matched_board_ranks = {
        rank
        for rank, total in combined_counts.items()
        if total >= 2 and hero_counts.get(rank, 0) > 0 and board_counts.get(rank, 0) > 0
    }
    if len(matched_board_ranks) >= 2:
        return True

    # Pocket pair that turns into a full house due to paired board (e.g., 88 on 8TT or 77 on KKQ).
    for rank, hero_cnt in hero_counts.items():
        if hero_cnt == 2:
            if board_counts.get(rank, 0) >= 1:
                return True  # set or quads
            if any(br != rank and bc >= 2 for br, bc in board_counts.items()):
                return True  # full house using board pair

    return False


def _has_overpair(hole: list[str], board: list[str]) -> bool:
    if len(hole) != 2:
        return False
    if hole[0] != hole[1]:
        return False
    if not board:
        return False
    board_max = max(_rank_values(board))
    return RANK_ORDER.get(hole[0], 0) > board_max


def _top_pair_category(hole: list[str], board: list[str]) -> tuple[bool, bool]:
    if not board:
        return (False, False)
    sorted_board = _sorted_board_ranks(board)
    if not sorted_board:
        return (False, False)
    top = sorted_board[0]
    second = sorted_board[1] if len(sorted_board) > 1 else None

    top_pair = False
    top_strong = False
    for card in hole:
        if card == top:
            top_pair = True
            kicker_rank = next((c for c in hole if c != top), None)
            kicker_value = RANK_ORDER.get(kicker_rank, 0) if kicker_rank else 0
            if kicker_value >= 12:  # Q+ kicker
                top_strong = True
    if top_pair:
        return (True, top_strong)

    if second is not None and second in hole:
        return (False, False)  # second pair handled later

    return (False, False)


def _is_second_pair(hole: list[str], board: list[str]) -> bool:
    sorted_board = _sorted_board_ranks(board)
    if len(sorted_board) < 2:
        return False
    second = sorted_board[1]
    return any(card == second for card in hole)


def _is_third_pair_or_under(hole: list[str], board: list[str]) -> bool:
    sorted_board = _sorted_board_ranks(board)
    if len(sorted_board) < 3:
        return False
    third = sorted_board[2]
    if any(card == third for card in hole):
        return True
    # Pocket pair below board top but not already classified as overpair.
    if len(hole) == 2 and hole[0] == hole[1]:
        board_max = max(_rank_values(board)) if board else 0
        return RANK_ORDER.get(hole[0], 0) < board_max
    return False


def _has_flush_draw(hole_cards: list[str], board_cards: list[str]) -> tuple[bool, bool]:
    has_flush, _ = _has_flush(hole_cards, board_cards)
    if has_flush:
        return False, False

    suits_total = Counter(c[-1] for c in hole_cards + board_cards)
    hero_cards = [parse_card(c) for c in hole_cards]
    hero_suits = Counter(s for _, s in hero_cards)
    for suit, total in suits_total.items():
        if total == 4 and hero_suits.get(suit, 0) >= 1:
            hero_ranks = [rank for rank, card_suit in hero_cards if card_suit == suit]
            return True, "A" in hero_ranks
    return (False, False)


def _has_flush(hole_cards: list[str], board_cards: list[str]) -> tuple[bool, bool]:
    suits_total = Counter(c[-1] for c in hole_cards + board_cards)
    if not suits_total:
        return False, False

    hero_cards = [parse_card(c) for c in hole_cards]
    hero_suits = Counter(s for _, s in hero_cards)
    for suit, total in suits_total.items():
        if total >= 5 and hero_suits.get(suit, 0) >= 1:
            hero_ranks = [rank for rank, card_suit in hero_cards if card_suit == suit]
            return True, "A" in hero_ranks
    return False, False


def _has_straight(hole_cards: list[str], board_cards: list[str]) -> bool:
    all_vals = sorted(_rank_value_set(hole_cards + board_cards))
    if len(all_vals) < 5:
        return False

    hero_vals = _rank_value_set(hole_cards)
    for i in range(len(all_vals) - 4):
        window = all_vals[i : i + 5]
        if window[-1] - window[0] == 4 and len(window) == 5:
            if hero_vals & set(window):
                return True
    return False


def _rank_value_set(cards: list[str], include_wheel: bool = True) -> set[int]:
    values = {_rank_value(card) for card in cards}
    # wheel handling: treat Ace as 1 as well when requested
    if include_wheel and 14 in values:
        values.add(1)
    return values


def _rank_value(card: str) -> int:
    rank, _ = parse_card(card)
    return RANK_ORDER.get(rank, 0)


def _has_open_ended_draw(hole_cards: list[str], board_cards: list[str]) -> bool:
    if _has_straight(hole_cards, board_cards):
        return False
    all_vals = sorted(_rank_value_set(hole_cards + board_cards))
    hero_vals = _rank_value_set(hole_cards, include_wheel=False)
    if len(all_vals) < 4 or not hero_vals:
        return False
    for i in range(len(all_vals) - 3):
        window = all_vals[i : i + 4]
        if window[-1] - window[0] == 3 and len(window) == 4:
            if hero_vals & set(window):
                return True
    return False


def _has_gutshot_draw(hole_cards: list[str], board_cards: list[str]) -> bool:
    if _has_straight(hole_cards, board_cards):
        return False
    all_vals = sorted(_rank_value_set(hole_cards + board_cards))
    hero_vals = _rank_value_set(hole_cards)
    if len(all_vals) < 4 or not hero_vals:
        return False
    for i in range(len(all_vals)):
        window = [v for v in all_vals if all_vals[i] <= v <= all_vals[i] + 4]
        if len(window) >= 4 and (hero_vals & set(window)):
            if not (len(window) == 4 and window[-1] - window[0] == 3):
                return True
    return False


def _has_backdoor_flush_draw(hole_cards: list[str], board_cards: list[str]) -> bool:
    if len(hole_cards) < 2:
        return False
    suits = {c[-1] for c in hole_cards}
    if len(suits) != 1:
        return False
    suit = next(iter(suits))
    return any(card.endswith(suit) for card in board_cards)


def _has_two_overcards(hole_cards: list[str], board_cards: list[str]) -> bool:
    if not board_cards:
        return False
    board_max = max(_rank_values([parse_card(c)[0] for c in board_cards]))
    hero_values = [_rank_value(c) for c in hole_cards]
    return all(v > board_max for v in hero_values)


def classify_postflop(hole_cards: list[str], board_cards: list[str]) -> str:
    board_ranks = [parse_card(c)[0] for c in board_cards]
    hole_ranks = [parse_card(c)[0] for c in hole_cards]

    if _has_two_pair_plus(hole_ranks, board_ranks):
        return "value_two_pair_plus"

    has_flush, _ = _has_flush(hole_cards, board_cards)
    if has_flush:
        return "value_two_pair_plus"

    if _has_straight(hole_cards, board_cards):
        return "value_two_pair_plus"

    top_pair, top_pair_strong = _top_pair_category(hole_ranks, board_ranks)
    if _has_overpair(hole_ranks, board_ranks) or (top_pair and top_pair_strong):
        return "overpair_or_tptk"

    if top_pair or _is_second_pair(hole_ranks, board_ranks):
        return "top_pair_weak_or_second"

    if _is_third_pair_or_under(hole_ranks, board_ranks):
        return "middle_pair_or_third_minus"

    fd, _ = _has_flush_draw(hole_cards, board_cards)
    oesd = _has_open_ended_draw(hole_cards, board_cards)
    if fd or oesd:
        return "strong_draw"

    gutshot = _has_gutshot_draw(hole_cards, board_cards)
    bdfd = _has_backdoor_flush_draw(hole_cards, board_cards)
    if gutshot or (bdfd and not fd):
        return "weak_draw"

    if _has_two_overcards(hole_cards, board_cards) and not bdfd:
        return "overcards_no_bdfd"

    return "air"


def classify_preflop(hole_cards: list[str]) -> str:
    if len(hole_cards) != 2:
        return "junk"
    ranks = [parse_card(c)[0] for c in hole_cards]
    suits = [parse_card(c)[1] for c in hole_cards]
    values = sorted((_rank_value(c) for c in hole_cards), reverse=True)
    pair = ranks[0] == ranks[1]

    if pair and values[0] >= RANK_ORDER["Q"]:
        return "premium_pair"

    broadway = {"A", "K", "Q", "J", "T"}
    if not pair and set(ranks).issubset(broadway):
        return "strong_broadway"

    if "A" in ranks and suits[0] == suits[1]:
        return "suited_ace"

    if pair:
        return "medium_pair"

    gap = abs(values[0] - values[1])
    if suits[0] == suits[1] and gap == 1 and 4 <= values[1] <= 10:
        return "suited_connectors"

    return "junk"


def generate_bucket_configs(seed: int = 42) -> dict[str, Mapping[str, object]]:
    features = ["strength", "potential"]
    meta = {"seed": int(seed)}

    def _build(street: str, bins: int, labels: list[str], rules: list[Mapping[str, object]]):
        return {
            "street": street,
            "version": 1,
            "bins": bins,
            "features": list(features),
            "labels": list(labels),
            "match_order": list(labels),
            "rules": [
                {
                    key: (list(value) if isinstance(value, list) else value)
                    for key, value in dict(rule).items()
                }
                for rule in rules
            ],
            "meta": dict(meta),
        }

    return {
        "preflop": _build("preflop", 6, _PRE_FLOP_LABELS, _PRE_FLOP_RULES),
        "flop": _build("flop", 8, _POST_FLOP_LABELS, _POST_FLOP_RULES),
        "turn": _build("turn", 8, _POST_FLOP_LABELS, _POST_FLOP_RULES),
    }


def assign_bucket(
    street: str,
    hole_cards: Iterable[str],
    board_cards: Iterable[str] | None = None,
    configs: Mapping[str, Mapping[str, object]] | None = None,
) -> tuple[int, str]:
    cfgs = configs or generate_bucket_configs()
    st = (street or "preflop").lower()
    if st not in cfgs:
        raise ValueError(f"Unsupported street: {street}")

    hole = _normalize_cards(hole_cards)
    board = _normalize_cards(board_cards or [])

    if st == "preflop":
        label = classify_preflop(hole)
    else:
        label = classify_postflop(hole, board)

    labels = list(cfgs[st]["labels"])  # type: ignore[index]
    if label not in labels:
        raise ValueError(f"Label {label} not defined for {st}")
    return labels.index(label), label


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build deterministic bucket configs (6-8-8).")
    parser.add_argument(
        "--streets", default="preflop,flop,turn", help="Comma separated streets to build"
    )
    parser.add_argument(
        "--bins", default="6,8,8", help="Comma separated bin counts for each street"
    )
    parser.add_argument(
        "--features", default="strength,potential", help="Comma separated feature names"
    )
    parser.add_argument(
        "--out", default="configs/buckets", help="Output directory for JSON configs"
    )
    parser.add_argument("--seed", default="42", help="Seed recorded in meta for reproducibility")
    args = parser.parse_args(argv)

    streets = [s.strip().lower() for s in args.streets.split(",") if s.strip()]
    bins = [int(b.strip()) for b in args.bins.split(",") if b.strip()]
    features = [f.strip() for f in args.features.split(",") if f.strip()]
    if len(streets) != len(bins):
        raise SystemExit("--streets and --bins must have the same arity")

    try:
        seed = int(args.seed)
    except ValueError as exc:
        raise SystemExit("--seed must be an integer") from exc

    configs = generate_bucket_configs(seed=seed)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    for street, bin_count in zip(streets, bins):
        if street not in configs:
            raise SystemExit(f"Unsupported street: {street}")
        config = dict(configs[street])
        config["features"] = features
        if config.get("bins") != bin_count:
            raise SystemExit(
                f"Bin mismatch for {street}: expected {config['bins']}, got {bin_count}"
            )
        path = out_dir / f"{street}.json"
        with path.open("w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2, ensure_ascii=False)

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
