"""Audit tool comparing runtime policy tables against rule-based baselines."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from poker_core.suggest.policy_loader import PolicyLoader
from poker_core.suggest.policy_loader import PolicyLoaderError


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit policy tables versus rules")
    parser.add_argument("--policy", required=True, help="Path to policy npz file or directory")
    parser.add_argument("--rules", required=True, help="Path to JSON rules mapping")
    parser.add_argument("--out", required=True, help="Markdown output path")
    parser.add_argument(
        "--threshold", type=float, default=0.6, help="Diff threshold triggering failure"
    )
    parser.add_argument(
        "--top", type=int, default=10, help="Maximum rows to include in summary table"
    )
    return parser.parse_args(argv)


def _load_policy_entries(path: Path) -> dict[str, Any]:
    loader = PolicyLoader(path)
    loader.warmup()
    return loader.snapshot()


def _load_rules(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):  # pragma: no cover - defensive
        raise ValueError("Rules file must contain a JSON object mapping node_key to config")
    return data


def _normalise(dist: dict[str, Any]) -> dict[str, float]:
    total = 0.0
    cleaned: dict[str, float] = {}
    for action, value in (dist or {}).items():
        try:
            weight = float(value)
        except Exception:
            weight = 0.0
        if weight < 0:
            weight = 0.0
        cleaned[str(action)] = weight
        total += weight
    if total <= 0:
        return {action: (1.0 if idx == 0 else 0.0) for idx, action in enumerate(cleaned)}
    return {action: weight / total for action, weight in cleaned.items()}


def _diff_rows(
    policies: dict[str, Any],
    rules: dict[str, Any],
    threshold: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    nodes = sorted(set(policies) | set(rules))
    rows: list[dict[str, Any]] = []
    violations: list[str] = []
    missing_policy: list[str] = []
    missing_rule: list[str] = []

    for node in nodes:
        policy_entry = policies.get(node)
        rule_entry = rules.get(node)
        if policy_entry is None:
            rows.append(
                {
                    "node_key": node,
                    "policy_top": None,
                    "rule_top": None,
                    "max_diff": 1.0,
                    "status": "missing_policy",
                    "policy_distribution": {},
                    "rule_distribution": (
                        _normalise((rule_entry or {}).get("actions", {}))
                        if isinstance(rule_entry, dict)
                        else {}
                    ),
                }
            )
            missing_policy.append(node)
            continue
        if rule_entry is None:
            rows.append(
                {
                    "node_key": node,
                    "policy_top": (
                        max(policy_entry.distribution().items(), key=lambda x: x[1])[0]
                        if policy_entry.distribution()
                        else None
                    ),
                    "rule_top": None,
                    "max_diff": 1.0,
                    "status": "missing_rule",
                    "policy_distribution": policy_entry.distribution(),
                    "rule_distribution": {},
                }
            )
            missing_rule.append(node)
            continue

        policy_dist = policy_entry.distribution()
        rule_dist = _normalise(rule_entry.get("actions", {}))
        actions = set(policy_dist) | set(rule_dist)
        diffs = [abs(policy_dist.get(a, 0.0) - rule_dist.get(a, 0.0)) for a in actions]
        max_diff = max(diffs) if diffs else 0.0
        status = "ok"
        if max_diff > threshold:
            status = "diff_exceeds"
            violations.append(node)

        policy_top = None
        if policy_dist:
            policy_top = max(policy_dist.items(), key=lambda x: x[1])[0]
        rule_top = None
        if rule_dist:
            rule_top = max(rule_dist.items(), key=lambda x: x[1])[0]

        rows.append(
            {
                "node_key": node,
                "policy_top": policy_top,
                "rule_top": rule_top,
                "max_diff": max_diff,
                "status": status,
                "policy_distribution": policy_dist,
                "rule_distribution": rule_dist,
            }
        )

    summary = {
        "violations": violations,
        "missing_policy": missing_policy,
        "missing_rule": missing_rule,
    }
    return rows, summary


def _row_sort_key(row: dict[str, Any]) -> tuple[int, float, str]:
    rank = {"diff_exceeds": 0, "missing_policy": 1, "missing_rule": 1, "ok": 2}
    status_rank = rank.get(row["status"], 3)
    return (status_rank, -float(row.get("max_diff", 0.0)), row["node_key"])


def _format_distribution(dist: dict[str, float]) -> str:
    if not dist:
        return "-"
    parts = [f"{action}:{weight:.2f}" for action, weight in sorted(dist.items())]
    return ", ".join(parts)


def _render_markdown(
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    *,
    threshold: float,
    top: int,
) -> str:
    lines = ["# Policy vs Rule Audit", ""]
    lines.append(f"- Threshold: {threshold:.2f}")
    lines.append(f"- Nodes audited: {len(rows)}")
    lines.append(f"- Threshold exceedances: {len(summary['violations'])}")
    lines.append(f"- Missing policy entries: {len(summary['missing_policy'])}")
    lines.append(f"- Missing rule entries: {len(summary['missing_rule'])}")
    lines.append("")
    lines.append(
        "| Node Key | Policy Top | Rule Top | Max Diff | Status | Policy Dist | Rule Dist |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")

    display_rows = sorted(rows, key=_row_sort_key)
    if top > 0:
        display_rows = display_rows[:top]

    for row in display_rows:
        node = row["node_key"]
        policy_top = row.get("policy_top") or "-"
        rule_top = row.get("rule_top") or "-"
        max_diff = float(row.get("max_diff", 0.0))
        status = row.get("status") or "ok"
        policy_dist = _format_distribution(row.get("policy_distribution", {}))
        rule_dist = _format_distribution(row.get("rule_distribution", {}))
        lines.append(
            f"| {node} | {policy_top} | {rule_top} | {max_diff:.2f} | {status} | {policy_dist} | {rule_dist} |"
        )

    if summary["violations"]:
        lines.append("")
        lines.append("## Nodes exceeding threshold")
        for node in summary["violations"]:
            lines.append(f"- {node}")

    if summary["missing_policy"]:
        lines.append("")
        lines.append("## Missing policy entries")
        for node in summary["missing_policy"]:
            lines.append(f"- {node}")

    if summary["missing_rule"]:
        lines.append("")
        lines.append("## Missing rule entries")
        for node in summary["missing_rule"]:
            lines.append(f"- {node}")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    policy_path = Path(args.policy)
    rules_path = Path(args.rules)
    out_path = Path(args.out)

    try:
        policies = _load_policy_entries(policy_path)
    except PolicyLoaderError as exc:
        print(f"Failed to load policy tables: {exc}")
        return 1

    try:
        rules = _load_rules(rules_path)
    except Exception as exc:  # pragma: no cover - input validation
        print(f"Failed to load rules: {exc}")
        return 1

    rows, summary = _diff_rows(policies, rules, float(args.threshold))
    report = _render_markdown(rows, summary, threshold=float(args.threshold), top=int(args.top))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    return 1 if summary["violations"] else 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
