"""Runtime loader for exported policy tables."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

import numpy as np

__all__ = [
    "PolicyEntry",
    "PolicyLoader",
    "PolicyLoaderError",
    "get_runtime_loader",
]

_LOG = logging.getLogger(__name__)
_EPS = 1e-9


@dataclass(frozen=True)
class PolicyEntry:
    """Single node entry within a policy table."""

    node_key: str
    actions: tuple[str, ...]
    weights: tuple[float, ...]
    size_tags: tuple[str | None, ...]
    meta: dict[str, Any]
    table_meta: dict[str, Any]
    raw_weights: tuple[float, ...]

    def distribution(self) -> dict[str, float]:
        return {
            action: float(weight)
            for action, weight in zip(self.actions, self.weights, strict=False)
        }


class PolicyLoaderError(RuntimeError):
    """Raised when policy tables cannot be loaded."""


class PolicyLoader:
    """Load and cache NPZ policy tables with automatic refresh on change."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        metrics: Any | None = None,
        mmap_mode: str | None = "r",
    ) -> None:
        self._root = Path(path)
        if not self._root.exists():
            raise PolicyLoaderError(f"Policy table path does not exist: {self._root}")
        self._metrics = metrics
        self._mmap_mode = mmap_mode
        self._lock = RLock()
        self._entries: dict[str, PolicyEntry] | None = None
        self._file_state: dict[Path, tuple[float, int]] = {}

    @property
    def root(self) -> Path:
        return self._root

    def warmup(self) -> None:
        """Force load tables eagerly."""

        self._ensure_loaded(force=True)

    def lookup(self, node_key: str) -> PolicyEntry | None:
        """Return the policy entry for ``node_key`` if available."""

        if not node_key:
            return None
        try:
            entries = self._ensure_loaded()
        except PolicyLoaderError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            raise PolicyLoaderError(f"Failed to load policy tables: {exc}") from exc

        entry = entries.get(node_key)
        if entry is None:
            self._emit_metric("policy_lookup_miss", node_key=node_key)
            _LOG.info("policy_lookup_miss node_key=%s", node_key)
            return None

        self._emit_metric("policy_lookup_hit", node_key=node_key)
        return entry

    def snapshot(self) -> dict[str, PolicyEntry]:
        """Return a copy of all cached entries."""

        entries = self._ensure_loaded()
        return dict(entries)

    def _emit_metric(self, name: str, **labels: Any) -> None:
        if self._metrics is None:
            return
        emit = getattr(self._metrics, "increment", None)
        if callable(emit):
            try:
                emit(name, **labels)
            except Exception:  # pragma: no cover - defensive
                _LOG.debug("metrics_emit_failed", exc_info=True)

    def _ensure_loaded(self, *, force: bool = False) -> dict[str, PolicyEntry]:
        with self._lock:
            if force or self._entries is None or self._sources_changed():
                self._entries = self._load_entries()
            return self._entries

    def _sources_changed(self) -> bool:
        current = self._current_state()
        if current.keys() != self._file_state.keys():
            self._file_state = current
            return True
        for path, info in current.items():
            if self._file_state[path] != info:
                self._file_state = current
                return True
        return False

    def _current_state(self) -> dict[Path, tuple[float, int]]:
        files = self._collect_sources()
        state: dict[Path, tuple[float, int]] = {}
        for path in files:
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            state[path] = (stat.st_mtime, stat.st_size)
        return state

    def _collect_sources(self) -> list[Path]:
        if self._root.is_file():
            return [self._root]
        if not self._root.is_dir():
            raise PolicyLoaderError(f"Policy path is neither file nor directory: {self._root}")
        files = sorted(self._root.glob("*.npz"))
        if not files:
            raise PolicyLoaderError(f"No policy npz files found under {self._root}")
        return files

    def _load_entries(self) -> dict[str, PolicyEntry]:
        files = self._collect_sources()
        entries: dict[str, PolicyEntry] = {}
        new_state: dict[Path, tuple[float, int]] = {}

        for path in files:
            try:
                stat = path.stat()
                new_state[path] = (stat.st_mtime, stat.st_size)
            except FileNotFoundError:
                continue
            try:
                with np.load(path, allow_pickle=True, mmap_mode=self._mmap_mode) as payload:
                    node_keys = list(payload["node_keys"])
                    actions = list(payload["actions"])
                    weights = list(payload["weights"])
                    size_tags = list(payload.get("size_tags", [() for _ in node_keys]))
                    metas = list(payload.get("meta", [{} for _ in node_keys]))
                    table_meta_raw = payload.get("table_meta")
            except KeyError as exc:
                raise PolicyLoaderError(f"Policy file {path} missing required field {exc}") from exc
            except Exception as exc:  # pragma: no cover - defensive
                raise PolicyLoaderError(f"Failed to load policy file {path}: {exc}") from exc

            table_meta: dict[str, Any] = {}
            if table_meta_raw is not None and len(table_meta_raw) > 0:
                table_meta = _coerce_mapping(table_meta_raw[0])

            for idx, node_key in enumerate(node_keys):
                key = str(node_key)
                acts = tuple(str(a) for a in actions[idx])
                size_tuple = tuple(_coerce_size_tag(tag) for tag in size_tags[idx])
                raw_weights_tuple = tuple(float(w) for w in weights[idx])
                total = sum(raw_weights_tuple)
                if total <= _EPS:
                    norm = tuple(1.0 if i == 0 else 0.0 for i in range(len(raw_weights_tuple)))
                else:
                    norm = tuple(w / total for w in raw_weights_tuple)
                meta = _coerce_mapping(metas[idx])
                entry = PolicyEntry(
                    node_key=key,
                    actions=acts,
                    weights=norm,
                    size_tags=size_tuple,
                    meta=meta,
                    table_meta=dict(table_meta),
                    raw_weights=raw_weights_tuple,
                )
                entries[key] = entry

        self._file_state = new_state
        return entries


def _coerce_size_tag(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    if not text or text.lower() in {"none", "na", "n/a"}:
        return None
    return text


def _coerce_mapping(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        mapping = dict(raw.item())  # type: ignore[attr-defined]
        return dict(mapping)
    except Exception:
        return {}


_RUNTIME_LOCK = RLock()
_RUNTIME_LOADER: PolicyLoader | None = None
_RUNTIME_PATH: Path | None = None


def get_runtime_loader() -> PolicyLoader | None:
    """Return a process-wide cached loader derived from environment settings."""

    path_str = os.getenv("SUGGEST_POLICY_DIR") or os.getenv("SUGGEST_POLICY_PATH")
    if not path_str:
        return None
    path = Path(path_str)

    global _RUNTIME_LOADER, _RUNTIME_PATH
    with _RUNTIME_LOCK:
        if _RUNTIME_LOADER is not None and _RUNTIME_PATH == path:
            return _RUNTIME_LOADER
        try:
            loader = PolicyLoader(path)
        except PolicyLoaderError:
            _LOG.exception("failed_to_initialise_policy_loader", extra={"path": str(path)})
            _RUNTIME_LOADER = None
            _RUNTIME_PATH = None
            return None
        _RUNTIME_LOADER = loader
        _RUNTIME_PATH = path
        return loader
