"""SHIM compat (reorg Phase 1.5) -> deplace en poles.fundamentals.external_feeds ; sys.modules preserve fundamentals.external_feeds."""
import sys as _sys
from poles.fundamentals import external_feeds as _mod
_sys.modules[__name__] = _mod
