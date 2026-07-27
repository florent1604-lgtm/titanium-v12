"""SHIM compat (reorg Phase 1.5) -> deplace en ingestion.market.spread_tracker ; sys.modules preserve data.spread_tracker."""
import sys as _sys
from ingestion.market import spread_tracker as _mod
_sys.modules[__name__] = _mod
