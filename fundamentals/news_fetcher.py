"""SHIM compat (reorg Phase 1.5) -> deplace en poles.fundamentals.news_fetcher ; sys.modules preserve fundamentals.news_fetcher."""
import sys as _sys
from poles.fundamentals import news_fetcher as _mod
_sys.modules[__name__] = _mod
