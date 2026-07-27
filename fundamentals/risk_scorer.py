"""SHIM compat (reorg Phase 1.5) -> deplace en poles.fundamentals.risk_scorer ; sys.modules preserve fundamentals.risk_scorer."""
import sys as _sys
from poles.fundamentals import risk_scorer as _mod
_sys.modules[__name__] = _mod
