"""SHIM compat (reorg Phase 1.5) -> deplace en ingestion.market.futures_data ; sys.modules preserve data.futures_data."""
import sys as _sys
from ingestion.market import futures_data as _mod
_sys.modules[__name__] = _mod
