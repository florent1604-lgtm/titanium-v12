"""core/cloe/ — NOYAU MÉMOIRE PERSISTANT de Cloe (le LLM local). Socle N0.

Cloe est une ENTITÉ, pas un modèle : son identité, sa mémoire, ses apprentissages vivent
ICI (hors du modèle), de façon persistante, hiérarchisée et documentée. Le modèle (Ollama)
n'est que le corps du moment. Cf. `core/cloe/memory.py` + `data/cloe/README.md`.
"""
from core.cloe.memory import Cloe, get_cloe  # noqa: F401
