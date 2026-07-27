"""SHIM compat (reorg Phase 1.5) -> deplace en poles.emotion.emotion_engine ; sys.modules preserve emotion.emotion_engine."""
import sys as _sys
from poles.emotion import emotion_engine as _mod
_sys.modules[__name__] = _mod
