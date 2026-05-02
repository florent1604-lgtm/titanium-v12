"""assistant/signal_alert.py — Alertes vocales automatiques via JARVIS.

Surveille les signaux Titanium et déclenche la voix de JARVIS (Edge TTS
fr-FR-HenriNeural) dès qu'un signal atteint un score ≥ 7/11.

Architecture :
    SignalAlertEngine (Titanium)
        └── WebSocket → ws://localhost:8765 (JARVIS)
                └── {"type": "direct_speak", "text": "..."} → parler()
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Dict, Optional

from utils.config import SYMBOLS

logger = logging.getLogger(__name__)

_JARVIS_WS_URL   = "ws://localhost:8765"
_WATCH_INTERVAL  = 10        # secondes entre chaque vérification
_CONNECT_TIMEOUT = 3.0       # timeout connexion WS JARVIS
_SEND_TIMEOUT    = 5.0       # timeout envoi message


class SignalAlertEngine:
    """Surveille les signaux Titanium et déclenche JARVIS vocalement."""

    SCORE_THRESHOLD: int  = 7    # score minimum sur 11
    COOLDOWN_SECONDS: int = 300  # 5 min entre deux alertes par paire
    MAX_QUEUE: int        = 3    # alertes simultanées max

    def __init__(self) -> None:
        self._task:          Optional[asyncio.Task] = None
        self._cooldowns:     Dict[str, float]       = {}   # sym → timestamp dernière alerte
        self._queue_count:   int                    = 0
        self._last_active:   Dict[str, bool]        = {}   # sym → was_active lors du dernier check

    # ── Cycle de vie ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Démarre la boucle de surveillance en arrière-plan."""
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._watch_loop(), name="signal-alert")
        logger.info(
            "[ALERT] Surveillance démarrée — seuil score ≥ %d, cooldown %ds",
            self.SCORE_THRESHOLD, self.COOLDOWN_SECONDS,
        )

    async def stop(self) -> None:
        """Arrête proprement la boucle."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[ALERT] Surveillance arrêtée")

    # ── Boucle principale ─────────────────────────────────────────────────────

    async def _watch_loop(self) -> None:
        """Interroge l'état des signaux toutes les _WATCH_INTERVAL secondes."""
        while True:
            try:
                await self._check_signals()
            except Exception as e:
                logger.debug("[ALERT] Erreur check: %s", e)
            await asyncio.sleep(_WATCH_INTERVAL)

    async def _check_signals(self) -> None:
        """Lit l'état courant et déclenche les alertes si les conditions sont remplies."""
        from execution.signal_manager import signals as _signals

        for sym in SYMBOLS:
            sig = _signals.get(sym, {})
            if not sig:
                continue

            score  = sig.get("score", 0)
            active = sig.get("active", False)
            side   = sig.get("side", "")

            was_active = self._last_active.get(sym, False)
            self._last_active[sym] = active

            # Signal doit être actif, qualifié, et nouveau (transition False→True)
            if not active or score < self.SCORE_THRESHOLD:
                continue

            # Ignorer si déjà actif lors du dernier check (évite les doublons)
            if was_active:
                continue

            if self._is_on_cooldown(sym):
                logger.debug("[ALERT] %s en cooldown — alerte ignorée", sym)
                continue

            if self._queue_count >= self.MAX_QUEUE:
                logger.warning("[ALERT] File pleine (%d) — alerte %s ignorée", self.MAX_QUEUE, sym)
                continue

            await self._trigger_alert(sym, sig)

    # ── Déclenchement ─────────────────────────────────────────────────────────

    async def _trigger_alert(self, symbol: str, signal: dict) -> None:
        """Déclenche l'alerte vocale via JARVIS WebSocket."""
        # Vérifier que le signal est toujours actif juste avant l'envoi
        from execution.signal_manager import signals as _signals
        current = _signals.get(symbol, {})
        if not current.get("active"):
            logger.debug("[ALERT] %s signal disparu avant envoi — annulé", symbol)
            return

        message = self._build_message(symbol, signal)
        self._cooldowns[symbol] = time.monotonic()
        self._queue_count += 1

        try:
            await self._send_to_jarvis(message)
            logger.info("[ALERT] Alerte vocale envoyée — %s score=%d %s",
                        symbol, signal.get("score"), signal.get("side"))
        except Exception as e:
            logger.warning("[ALERT] Échec envoi JARVIS pour %s: %s", symbol, e)
        finally:
            self._queue_count = max(0, self._queue_count - 1)

    async def _send_to_jarvis(self, text: str) -> None:
        """Envoie un message direct_speak au WebSocket JARVIS."""
        try:
            import websockets
        except ImportError:
            raise RuntimeError("websockets non installé")

        payload = json.dumps({"type": "direct_speak", "text": text})
        async with websockets.connect(
            _JARVIS_WS_URL,
            open_timeout=_CONNECT_TIMEOUT,
            close_timeout=2.0,
        ) as ws:
            await asyncio.wait_for(ws.send(payload), timeout=_SEND_TIMEOUT)

    # ── Construction du message ───────────────────────────────────────────────

    def _build_message(self, symbol: str, signal: dict) -> str:
        """Construit le message vocal en français naturel."""
        score  = signal.get("score",  0)
        side   = signal.get("side",   "NEUTRE")
        price  = signal.get("price",  0.0)
        confs  = signal.get("confs",  [])
        regime = signal.get("regime", "")
        rr     = signal.get("rr",     0.0)
        tp1    = signal.get("tp1",    0.0)
        sl     = signal.get("sl",     0.0)

        # Nom de la paire lisible
        base = symbol.split("/")[0]
        name_map = {"BTC": "Bitcoin", "PAXG": "PAX Gold", "ETH": "Ethereum",
                    "SOL": "Solana", "XAU": "Or"}
        name = name_map.get(base, base)

        # Direction
        direction = "achat" if side == "ACHAT" else "vente" if side == "VENTE" else "neutre"

        # Qualité du signal
        if score >= 10:
            qualite = "signal parfait"
        elif score >= 8:
            qualite = "signal premium"
        elif score >= 7:
            qualite = "setup fort"
        else:
            qualite = "setup détecté"

        # Message de base
        msg = (
            f"Alerte trading, Florent. {qualite} sur {name}. "
            f"Direction {direction}, score {score} sur 11. "
            f"Prix actuel {price:,.0f}."
        )

        # Ajouter confirmations clés (max 2)
        conf_labels = {
            "CHoCH":        "changement de structure",
            "BOS":          "cassure de structure",
            "OB":           "order block",
            "FVG":          "fair value gap",
            "EMA200_H4":    "biais EMA 200",
            "RSI":          "RSI favorable",
            "DELTA_VOL":    "delta volume confirmé",
            "FUNDING":      "funding rate favorable",
        }
        conf_parts = [conf_labels[c] for c in confs[:2] if c in conf_labels]
        if conf_parts:
            msg += f" Confirmations : {', '.join(conf_parts)}."

        # SL/TP si disponibles
        if tp1 > 0 and sl > 0 and rr > 0:
            msg += f" Risk reward {rr:.1f}."

        # Régime
        if regime == "TREND":
            msg += " Marché en tendance."

        return msg

    # ── Cooldown ──────────────────────────────────────────────────────────────

    def _is_on_cooldown(self, symbol: str) -> bool:
        """Vérifie si une alerte a déjà été envoyée récemment pour ce symbole."""
        last = self._cooldowns.get(symbol)
        if last is None:
            return False
        return (time.monotonic() - last) < self.COOLDOWN_SECONDS


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: Optional[SignalAlertEngine] = None


def get_signal_alert_engine() -> SignalAlertEngine:
    global _engine
    if _engine is None:
        _engine = SignalAlertEngine()
    return _engine
