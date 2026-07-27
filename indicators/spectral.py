"""SHIM compat (reorg Phase 1.5) -> deplace en poles.spectral.spectral ; sys.modules preserve indicators.spectral."""
import sys as _sys
from poles.spectral import spectral as _mod
_sys.modules[__name__] = _mod
