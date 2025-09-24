import random
from dataclasses import dataclass


@dataclass
class RNG:
    seed: int | None
    algo: str = "mt19937"
    version: str = "py-random"

    def create(self) -> random.Random:
        r = random.Random()
        if self.seed is not None:
            r.seed(self.seed)
        return r
