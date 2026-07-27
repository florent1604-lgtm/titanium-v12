"""SHIM compat (reorg Phase 1.5) -> deplace en ingestion.market.orderbook_ws ; sys.modules preserve data.orderbook_ws."""
import sys as _sys
from ingestion.market import orderbook_ws as _mod
_sys.modules[__name__] = _mod
