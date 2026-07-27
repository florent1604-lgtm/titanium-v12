"""SHIM compat (reorg Phase 1.5) -> deplace en ingestion.market.gold_provider ; sys.modules preserve data.gold_provider."""
import sys as _sys
from ingestion.market import gold_provider as _mod
_sys.modules[__name__] = _mod
