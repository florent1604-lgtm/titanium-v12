"""SHIM compat (reorg Phase 1.5) -> deplace en ingestion.market.binance_kline_feed ; sys.modules preserve data.binance_kline_feed."""
import sys as _sys
from ingestion.market import binance_kline_feed as _mod
_sys.modules[__name__] = _mod
