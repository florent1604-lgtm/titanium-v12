"""notifications/telegram.py — Alertes Telegram avec seuil dynamique et anti-spam."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict
import aiohttp
from utils.config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS, TELEGRAM_MIN_INTERVAL,
    TELEGRAM_SCORE_THRESHOLD, TELEGRAM_SCORE_LABELS, SYMBOLS, SCORE_CRITERIA,
)
from utils.logger import get_logger

logger = get_logger(__name__)
_last_sent: Dict[str, float] = {s: 0.0 for s in SYMBOLS}
_tg_lock = asyncio.Lock()


def _format_signal(sym: str, signal: Dict[str, Any]) -> str:
    """Formate le message Telegram avec détail des confirmations."""
    score   = signal.get("score", 0)
    score_max = signal.get("score_max", len(SCORE_CRITERIA))
    side    = signal.get("side", "?")
    price   = signal.get("price", 0)
    label   = TELEGRAM_SCORE_LABELS.get(score, "Signal")
    confs   = signal.get("confs", [])
    regime  = signal.get("regime", "?")
    sl      = signal.get("sl", 0)
    tp1     = signal.get("tp1", 0)
    tp2     = signal.get("tp2", 0)
    tp3     = signal.get("tp3", 0)
    rsi     = signal.get("rsi", 0)
    adx     = signal.get("adx", 0)

    side_emoji = "🟢" if "ACHAT" in side else "🔴"
    sym_clean  = sym.replace("/", "")

    conf_lines = "\n".join(f"  ✅ {c}" for c in confs) if confs else "  (aucune)"

    return (
        f"{label}\n"
        f"<b>{sym_clean}</b> {side_emoji} <b>{side}</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📊 Score : <b>{score}/{score_max}</b>\n"
        f"💰 Prix  : <b>{price:,.2f}</b>\n"
        f"📈 Régime: {regime} | RSI: {rsi:.1f} | ADX: {adx:.1f}\n"
        f"\n<b>Confirmations :</b>\n{conf_lines}\n"
        f"\n<b>Niveaux :</b>\n"
        f"  🛑 SL  : {sl:,.2f}\n"
        f"  🎯 TP1 : {tp1:,.2f}\n"
        f"  🎯 TP2 : {tp2:,.2f}\n"
        f"  🎯 TP3 : {tp3:,.2f}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"<i>Titanium v12 — {datetime.now(timezone.utc).strftime('%H:%M UTC')}</i>"
    )


async def send_signal_alert(
    session: aiohttp.ClientSession,
    sym: str,
    signal: Dict[str, Any],
    force: bool = False,
) -> None:
    """Envoie une alerte Telegram si le score dépasse le seuil et respecte l'anti-spam."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_IDS:
        return

    score = signal.get("score", 0)
    if score < TELEGRAM_SCORE_THRESHOLD:
        return

    now  = datetime.now(timezone.utc).timestamp()
    async with _tg_lock:
        last = _last_sent.get(sym, 0.0)
        if not force and (now - last) < TELEGRAM_MIN_INTERVAL:
            logger.debug("[TG] Anti-spam %s — %ds restants", sym, int(TELEGRAM_MIN_INTERVAL - (now - last)))
            return
        _last_sent[sym] = now

    text = _format_signal(sym, signal)
    url  = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            async with session.post(
                url,
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                      "disable_web_page_preview": True},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                if r.status != 200:
                    body = await r.text()
                    logger.warning("[TG] HTTP %s chat=%s: %s", r.status, chat_id, body[:80])
                else:
                    logger.info("[TG] Alerte envoyée %s score=%d", sym, score)
        except Exception as e:
            logger.error("[TG] Erreur envoi %s: %s", sym, e)
