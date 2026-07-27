"""SHIM compat (reorg Phase 1.5) -> deplace en ingestion.market.binance_ws ; sys.modules preserve data.binance_ws."""
import sys as _sys
from ingestion.market import binance_ws as _mod
_sys.modules[__name__] = _mod
