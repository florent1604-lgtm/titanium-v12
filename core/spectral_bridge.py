"""SHIM compat (reorg Phase 1.5) -> deplace en poles.spectral.spectral_bridge ; sys.modules preserve core.spectral_bridge."""
import sys as _sys
from poles.spectral import spectral_bridge as _mod
_sys.modules[__name__] = _mod
