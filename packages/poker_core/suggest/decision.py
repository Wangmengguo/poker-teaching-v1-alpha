"""Decision primitives shared between policies and service layer."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from poker_core.domain.actions import LegalAction

from .calculators import size_from_bb, size_from_tag
from .codes import CodeDef, SCodes
from .codes import mk_rationale as R
from .context import SuggestContext
from .types import Observation, PolicyConfig
from .utils import raise_to_amount


@dataclass(frozen=True)
class SizeSpec:
    kind: str
    value: float | str | int

    @classmethod
    def bb(cls, mult: float) -> SizeSpec:
        return cls("bb", float(mult))

    @classmethod
    def tag(cls, tag: str) -> SizeSpec:
        return cls("tag", str(tag))

    @classmethod
    def amount(cls, amount: int) -> SizeSpec:
        return cls("amount", int(amount))


@dataclass
class Decision:
    action: str
    sizing: SizeSpec | None = None
    meta: dict | None = None
    rationale: list[dict] | None = None
    min_reopen_code: CodeDef | None = None

    def resolve(
        self,
        obs: Observation,
        acts: Iterable[LegalAction],
        cfg: PolicyConfig,
    ) -> tuple[dict[str, int | str], dict, list[dict]]:
        suggested: dict[str, int | str] = {"action": self.action}
        meta = dict(self.meta or {})
        rationale: list[dict] = list(self.rationale or [])

        if self.action in {"bet", "raise", "allin"} and self.sizing is not None:
            amount = self._amount_from_sizing(obs, acts, rationale)
            if amount is not None:
                suggested["amount"] = amount

        return suggested, meta, rationale

    def _amount_from_sizing(
        self,
        obs: Observation,
        acts: Iterable[LegalAction],
        rationale: list[dict],
    ) -> int | None:
        if self.sizing is None:
            return None

        kind = self.sizing.kind
        acts_list = list(acts or [])

        if kind == "amount":
            amount = int(self.sizing.value)
        elif kind == "bb":
            amount = int(size_from_bb(float(self.sizing.value), int(obs.bb or 1)))
        elif kind == "tag":
            if self.action == "raise":
                ctx = obs.context or SuggestContext.build()
                modes = ctx.modes.get("HU", {}) if isinstance(ctx.modes, dict) else {}
                cap_ratio = float(modes.get("postflop_cap_ratio", 0.85))
                amount = raise_to_amount(
                    pot_now=int(getattr(obs, "pot_now", obs.pot) or 0),
                    last_bet=int(getattr(obs, "last_bet", 0) or 0),
                    size_tag=str(self.sizing.value),
                    bb=int(obs.bb or 1),
                    eff_stack=None,
                    cap_ratio=cap_ratio,
                )
            else:
                amount = size_from_tag(
                    size_tag=str(self.sizing.value),
                    pot_now=int(getattr(obs, "pot_now", obs.pot) or 0),
                    last_bet=int(getattr(obs, "last_bet", 0) or 0),
                    bb=int(obs.bb or 1),
                )
        else:
            amount = None

        if amount is None:
            return None

        if self.action == "raise":
            raise_act = next((a for a in acts_list if a.action == "raise"), None)
            if raise_act and raise_act.min is not None and amount < int(raise_act.min):
                amount = int(raise_act.min)
                code = self.min_reopen_code or SCodes.FL_MIN_REOPEN_ADJUSTED
                rationale.append(R(code))

        return int(amount)


__all__ = ["Decision", "SizeSpec"]
