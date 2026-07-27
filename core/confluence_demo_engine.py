"""SHIM compat (reorg Phase 1.5) -> deplace en fusion.confluence_demo_engine ; sys.modules preserve core.confluence_demo_engine."""
import sys as _sys
from fusion import confluence_demo_engine as _mod
_sys.modules[__name__] = _mod
