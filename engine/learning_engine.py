"""SHIM de compatibilité (réorg Phase 1.5) — déplacé en `feedback/learning_engine.py`.
Réassigne `sys.modules` : `from engine.learning_engine import ...` reste valide. À retirer
après migration des importeurs vers `feedback.learning_engine`."""
import sys as _sys
from feedback import learning_engine as _mod
_sys.modules[__name__] = _mod
