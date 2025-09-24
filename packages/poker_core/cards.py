SUITS = ["s", "h", "d", "c"]  # spades, hearts, diamonds, clubs
RANKS = ["A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"]  # 按强度降序

RANK_ORDER: dict[str, int] = {rank: 14 - i for i, rank in enumerate(RANKS)}
SUIT_NAMES = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}


def make_deck() -> list[str]:
    return [rank + suit for rank in RANKS for suit in SUITS]


def parse_card(card: str) -> tuple[str, str]:
    if len(card) != 2:
        raise ValueError(f"Invalid card format: {card}")
    return card[0], card[1]


def get_rank_value(rank: str) -> int:
    return RANK_ORDER[rank]
