"""SHIM compat (reorg Phase 1.5) -> deplace en fusion.consensus_engine ; sys.modules preserve core.consensus_engine."""
import sys as _sys
from fusion import consensus_engine as _mod
_sys.modules[__name__] = _mod
