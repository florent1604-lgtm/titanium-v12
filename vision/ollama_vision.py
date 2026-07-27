"""SHIM compat (reorg Phase 1.5) -> deplace en poles.vision.ollama_vision ; sys.modules preserve vision.ollama_vision."""
import sys as _sys
from poles.vision import ollama_vision as _mod
_sys.modules[__name__] = _mod
