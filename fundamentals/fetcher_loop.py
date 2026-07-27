"""SHIM compat (reorg Phase 1.5) -> deplace en poles.fundamentals.fetcher_loop ; sys.modules preserve fundamentals.fetcher_loop."""
import sys as _sys
from poles.fundamentals import fetcher_loop as _mod
_sys.modules[__name__] = _mod
