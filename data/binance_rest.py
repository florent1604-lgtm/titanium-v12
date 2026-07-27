"""SHIM compat (reorg Phase 1.5) -> deplace en ingestion.market.binance_rest ; sys.modules preserve data.binance_rest."""
import sys as _sys
from ingestion.market import binance_rest as _mod
_sys.modules[__name__] = _mod
