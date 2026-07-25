"""execution/trade_alert.py — alerte SONORE à l'ouverture d'un trade démo.

Beep serveur (haut-parleurs de la machine, sans navigateur nécessaire) + voix
JARVIS/Titan best-effort. Garde-fou ABSOLU : ne peut JAMAIS casser un ordre ni
la boucle — toute exception est avalée, le beep tourne dans un thread daemon.
"""
from __future__ import annotations

import threading

from utils.logger import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_count = 0


def _beep_pattern() -> None:
    """3 bips ascendants distinctifs (Windows). Repli cloche console sinon."""
    try:
        import winsound  # Windows uniquement
        for freq in (880, 1175, 1568):   # motif reconnaissable "trade ouvert"
            winsound.Beep(freq, 170)
    except Exception:
        try:
            print("\a", end="", flush=True)
        except Exception:
            pass


def demo_trade_opened(symbol: str, side: str, *, first_only: bool = False) -> None:
    """Signale sonorement l'ouverture d'un trade démo. Non bloquant, fail-safe.

    first_only=True → ne sonne QUE pour le tout premier trade de la session.
    Par défaut sonne à CHAQUE ouverture (le premier inclus)."""
    global _count
    try:
        with _lock:
            _count += 1
            n = _count
        if first_only and n > 1:
            return
        threading.Thread(target=_beep_pattern, daemon=True).start()
        # Voix best-effort (comme opportunity_scan._voice_alert) — jamais bloquant.
        msg = f"Trade démo ouvert : {side} {symbol}"
        for mod, fn in (("assistant.titan_core", "speak"),
                        ("assistant.signal_alert", "speak_alert")):
            try:
                m = __import__(mod, fromlist=[fn])
                getattr(m, fn)(msg)
                break
            except Exception:
                continue
        logger.info("[ALERTE] trade démo #%d ouvert : %s %s", n, side, symbol)
    except Exception as exc:  # noqa: BLE001 — l'alerte ne doit JAMAIS casser un ordre
        try:
            logger.debug("[ALERTE] échec non bloquant: %s", exc)
        except Exception:
            pass
