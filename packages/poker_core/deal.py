from .cards import make_deck
from .rng import RNG


def deal_hand(seed: int | None = None, num_players: int = 2):
    assert 2 <= num_players <= 6, "players must be 2..6"
    rng = RNG(seed=seed)
    rnd = rng.create()
    deck = make_deck()
    rnd.shuffle(deck)

    steps = [
        {
            "idx": 0,
            "evt": "DECK_INIT",
            "payload": {"algo": rng.algo, "cards": len(deck)},
        }
    ]
    players = []
    for p in range(num_players):
        hole = [deck.pop(), deck.pop()]
        steps.append({"idx": len(steps), "evt": "DEAL_HOLE", "payload": {"p": p, "cards": hole}})
        players.append({"pos": p, "hole": hole})

    return {
        "seed": seed if seed is not None else None,
        "players": players,
        "steps": steps,
    }
