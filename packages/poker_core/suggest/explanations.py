from __future__ import annotations

import os
from collections import UserDict
from dataclasses import dataclass
from string import Formatter
from typing import Any

from .config_loader import load_json_cached

"""Render rationale items into human‑readable explanations (i18n‑ready).

Public API:
- load_explanations(locale='zh') -> dict[str, str]
- render_explanations(rationale: list[dict], meta: dict | None, extras: dict | None) -> list[str]

This module is intentionally lightweight and has zero external deps.
"""


def load_explanations(locale: str = "zh") -> dict[str, str]:
    """Load templates for a locale with TTL caching and graceful fallback.

    File naming convention: explanations_<locale>.json under config/.
    Falls back to zh when requested locale is missing.
    """
    fn = f"explanations_{(locale or 'zh').lower()}.json"
    data, _ = load_json_cached(fn, ttl_seconds=60)
    if data:
        return {str(k): str(v) for k, v in data.items() if isinstance(v, str)}
    if (locale or "").lower() != "zh":
        data, _ = load_json_cached("explanations_zh.json", ttl_seconds=60)
        return {str(k): str(v) for k, v in (data or {}).items() if isinstance(v, str)}
    return {}


@dataclass
class _SafeMap(UserDict):
    """A dict that leaves unknown placeholders intact during format_map()."""

    def __missing__(self, key: str) -> str:
        return "{" + str(key) + "}"


def _format_template(tpl: str, ctx: dict[str, Any]) -> str:
    """Robust formatting: apply per-field formatting; keep unknown fields intact."""
    try:
        parts: list[str] = []
        for literal, field, fmt_spec, conv in Formatter().parse(str(tpl)):
            parts.append(literal or "")
            if not field:
                continue
            if field in ctx:
                val = ctx[field]
                try:
                    if conv == "s":
                        val = str(val)
                    elif conv == "r":
                        val = repr(val)
                    elif conv == "a":
                        val = ascii(val)
                except Exception:
                    pass
                try:
                    text = format(val, fmt_spec or "")
                except Exception:
                    text = str(val)
            else:
                # keep original placeholder with spec when unknown
                if fmt_spec:
                    text = "{" + field + ":" + fmt_spec + "}"
                else:
                    text = "{" + field + "}"
            parts.append(text)
        return "".join(parts)
    except Exception:
        return str(tpl)


def render_explanations(
    rationale: list[dict] | None,
    meta: dict | None = None,
    extras: dict | None = None,
) -> list[str]:
    """Render rationale items to strings using templates + context data.

    Precedence for template variables: rationale.data/meta → meta → extras
    If no template for a code, fall back to rationale.msg/message/code.
    """
    items = list(rationale or [])
    locale = (os.getenv("SUGGEST_LOCALE") or "zh").strip().lower()
    mapping = load_explanations(locale)
    out: list[str] = []
    for r in items:
        try:
            code = str((r or {}).get("code") or "")
        except Exception:
            code = ""
        # choose template
        tpl = mapping.get(code) or r.get("msg") or r.get("message") or code or ""
        # merge context
        ctx: dict[str, Any] = {}
        data = r.get("data")
        if isinstance(data, dict):
            ctx.update(data)
        meta_val = r.get("meta")
        if isinstance(meta_val, dict):
            ctx.update(meta_val)
        if isinstance(meta, dict):
            ctx.update(meta)
        if isinstance(extras, dict):
            ctx.update(extras)
        out.append(_format_template(str(tpl), ctx).strip())
    return [s for s in out if s]


__all__ = ["load_explanations", "render_explanations"]
