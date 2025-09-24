from __future__ import annotations

import json
from typing import Any

from poker_core.suggest.flop_rules import load_flop_rules


def _validate_rules(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if "single_raised" not in data:
        errors.append("missing key: single_raised")
        return errors
    node = data["single_raised"]
    if "role" not in node:
        errors.append("missing key: role under single_raised")
        return errors
    for role in ("pfr", "caller"):
        rnode = (node["role"] or {}).get(role)
        if not isinstance(rnode, dict):
            errors.append(f"missing role node: {role}")
            continue
        for pos in ("ip", "oop"):
            pnode = rnode.get(pos) or {}
            if not isinstance(pnode, dict):
                errors.append(f"missing ip/oop node: {role}.{pos}")
                continue
            # texture defaults
            has_any = any(k in pnode for k in ("dry", "semi", "wet", "defaults"))
            if not has_any:
                errors.append(f"no texture keys under {role}.{pos}")
            # ensure each texture has defaults (when present)
            for tex in ("dry", "semi", "wet"):
                tnode = pnode.get(tex) or {}
                if not isinstance(tnode, dict):
                    continue
                if "defaults" not in tnode:
                    errors.append(f"missing defaults under {role}.{pos}.{tex}")
    return errors


def test_flop_rules_medium_schema_gate():
    data, ver = load_flop_rules("medium")
    errs = _validate_rules(data)
    if errs:
        raise AssertionError(
            "medium rules schema invalid:\n" + json.dumps(errs, ensure_ascii=False, indent=2)
        )


def test_flop_rules_loose_tight_smoke():
    # smoke, non-blocking: just ensure load works and returns dicts
    for s in ("loose", "tight"):
        data, ver = load_flop_rules(s)
        assert isinstance(data, dict)
