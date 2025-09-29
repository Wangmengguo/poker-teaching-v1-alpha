"""Compatibility wrapper for the legacy :mod:`tools.lp_solver` module."""

from __future__ import annotations

import warnings

from .solve_lp import *  # noqa: F401,F403 - re-export for backwards compatibility
from .solve_lp import __all__ as _SOLVE_LP_ALL

__all__ = list(_SOLVE_LP_ALL)

warnings.warn(
    "tools.lp_solver is deprecated; import from tools.solve_lp instead",
    DeprecationWarning,
    stacklevel=2,
)
