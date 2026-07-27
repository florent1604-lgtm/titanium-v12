"""SHIM compat (reorg Phase 1.5) -> deplace en poles.smc.smc_engine ; sys.modules preserve core.smc_engine."""
import sys as _sys
from poles.smc import smc_engine as _mod
_sys.modules[__name__] = _mod
