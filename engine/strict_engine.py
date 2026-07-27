"""SHIM de compatibilité (réorg Phase 1.5) — déplacé en `feedback/strict_engine.py`.
Réassigne `sys.modules` : `from engine.strict_engine import ...` reste valide. À retirer
après migration des importeurs vers `feedback.strict_engine`."""
import sys as _sys
from feedback import strict_engine as _mod
_sys.modules[__name__] = _mod
