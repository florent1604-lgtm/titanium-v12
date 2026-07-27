"""SHIM compat (reorg Phase 1.5) -> deplace en poles.spectral.geometric_plane ; sys.modules preserve core.geometric_plane."""
import sys as _sys
from poles.spectral import geometric_plane as _mod
_sys.modules[__name__] = _mod
