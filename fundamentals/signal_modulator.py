"""SHIM compat (reorg Phase 1.5) -> deplace en poles.fundamentals.signal_modulator ; sys.modules preserve fundamentals.signal_modulator."""
import sys as _sys
from poles.fundamentals import signal_modulator as _mod
_sys.modules[__name__] = _mod
