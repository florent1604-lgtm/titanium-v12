"""SHIM compat (reorg Phase 1.5) -> deplace en fusion.confluence_adapter ; sys.modules preserve core.confluence_adapter."""
import sys as _sys
from fusion import confluence_adapter as _mod
_sys.modules[__name__] = _mod
