"""SHIM compat (reorg Phase 1.5) -> deplace en poles.smc.signal_engine ; sys.modules preserve core.signal_engine."""
import sys as _sys
from poles.smc import signal_engine as _mod
_sys.modules[__name__] = _mod
