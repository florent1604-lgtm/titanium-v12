"""SHIM compat (reorg Phase 1.5) -> deplace en poles.emotion.market_context ; sys.modules preserve emotion.market_context."""
import sys as _sys
from poles.emotion import market_context as _mod
_sys.modules[__name__] = _mod
