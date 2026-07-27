"""SHIM compat (reorg Phase 1.5) -> deplace en ingestion.market.mt5_provider ; sys.modules preserve data.mt5_provider."""
import sys as _sys
from ingestion.market import mt5_provider as _mod
_sys.modules[__name__] = _mod
