"""SHIM de compatibilité (réorg Phase 1.5) — le module a été déplacé en `feedback/optimizer.py`.
Ce shim réassigne `sys.modules` pour que `from engine.optimizer import ...` (anciens imports,
noms publics ET privés) continue de fonctionner à l'identique. À retirer quand tous les
importeurs auront migré vers `feedback.optimizer`."""
import sys as _sys
from feedback import optimizer as _mod
_sys.modules[__name__] = _mod
