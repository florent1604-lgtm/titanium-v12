"""SHIM compat (reorg Phase 1.5) -> deplace en ingestion.market.binance_ohlcv ; sys.modules preserve data.binance_ohlcv."""
import sys as _sys
from ingestion.market import binance_ohlcv as _mod
_sys.modules[__name__] = _mod
