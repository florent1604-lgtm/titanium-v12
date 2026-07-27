"""SHIM compat (reorg Phase 1.5) -> deplace en fusion.cortex ; sys.modules preserve core.cortex."""
import sys as _sys
from fusion import cortex as _mod
_sys.modules[__name__] = _mod
