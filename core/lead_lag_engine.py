"""SHIM compat (reorg Phase 1.5) -> deplace en fusion.lead_lag_engine ; sys.modules preserve core.lead_lag_engine."""
import sys as _sys
from fusion import lead_lag_engine as _mod
_sys.modules[__name__] = _mod
