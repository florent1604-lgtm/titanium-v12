"""SHIM compat (reorg Phase 1.5) -> deplace en fusion.confluence_gate ; sys.modules preserve core.confluence_gate."""
import sys as _sys
from fusion import confluence_gate as _mod
_sys.modules[__name__] = _mod
