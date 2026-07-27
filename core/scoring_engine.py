"""SHIM compat (reorg Phase 1.5) -> deplace en poles.smc.scoring_engine ; sys.modules preserve core.scoring_engine."""
import sys as _sys
from poles.smc import scoring_engine as _mod
_sys.modules[__name__] = _mod
