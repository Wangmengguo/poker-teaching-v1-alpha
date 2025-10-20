from __future__ import annotations

import csv
import os
import statistics
from collections.abc import Iterable
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from math import sqrt


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def timestamp_tag() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def mean_and_ci95(values: Sequence[float]) -> tuple[float, float | None, float | None]:
    if not values:
        return 0.0, None, None
    m = statistics.fmean(values)
    if len(values) < 2:
        return m, None, None
    sd = statistics.stdev(values)
    se = sd / sqrt(len(values))
    # Normal approx; sufficient for our batch sizes
    delta = 1.96 * se
    return m, m - delta, m + delta


def bb_per_100_from_totals(total_pnl_chips: float, total_hands: int, bb_size: float) -> float:
    if total_hands <= 0 or bb_size <= 0:
        return 0.0
    pnl_bb = total_pnl_chips / float(bb_size)
    return 100.0 * pnl_bb / float(total_hands)


def write_csv(path: str, headers: Iterable[str], rows: Iterable[Iterable[object]]) -> None:
    _ensure_parent_dir(path)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(list(headers))
        for r in rows:
            w.writerow(list(r))


def write_markdown_summary(path: str, title: str, kv_pairs: Iterable[tuple[str, object]]) -> None:
    _ensure_parent_dir(path)
    lines: list[str] = [f"### {title}", ""]
    for k, v in kv_pairs:
        lines.append(f"- **{k}**: {v}")
    content = "\n".join(lines) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


@dataclass
class SuggestCounters:
    total_calls: int = 0
    policy_hits: int = 0
    rule_fallbacks: int = 0
    fallback_used: int = 0
    facing_fallbacks: int = 0
    alias_applied: int = 0
    clamped: int = 0
    total_latency_ms: float = 0.0

    def observe(self, resp: dict, latency_sec: float) -> None:
        self.total_calls += 1
        meta = resp.get("meta") or {}
        src = (meta.get("policy_source") or "").strip().lower()
        if src == "policy":
            self.policy_hits += 1
        elif src == "rule":
            self.rule_fallbacks += 1
        # Count fallback only once per response. The service sets both
        # policy_source="fallback" and fallback_used=True when fallback happens.
        elif src == "fallback":
            self.fallback_used += 1
        # If source wasn't marked fallback but explicit flag is present, count it.
        elif bool(meta.get("fallback_used")):
            self.fallback_used += 1
        if meta.get("facing_fallback"):
            self.facing_fallbacks += 1
        if meta.get("facing_alias_applied"):
            self.alias_applied += 1
        rationale = resp.get("rationale") or []
        try:
            if any((it or {}).get("code") == "W_CLAMPED" for it in rationale):
                self.clamped += 1
        except Exception:
            pass
        try:
            self.total_latency_ms += float(latency_sec) * 1000.0
        except Exception:
            pass

    def to_row(self) -> list[object]:
        mean_latency = (self.total_latency_ms / self.total_calls) if self.total_calls else 0.0
        return [
            self.total_calls,
            self.policy_hits,
            self.rule_fallbacks,
            self.fallback_used,
            self.facing_fallbacks,
            self.alias_applied,
            self.clamped,
            round(mean_latency, 3),
        ]

    @staticmethod
    def headers() -> list[str]:
        return [
            "suggest_calls",
            "policy_hits",
            "rule_fallbacks",
            "fallback_used",
            "facing_fallbacks",
            "alias_applied",
            "clamped",
            "mean_latency_ms",
        ]
