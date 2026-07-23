"""notifications/telegram.py — Alertes Telegram avec seuil dynamique et anti-spam.

Deux canaux :
  · `send_signal_alert` — legacy, sur l'ancien score /16 du signal_engine.
  · `send_confluence_alert` — NOUVEAUX indicateurs : les 5 piliers de la méthode de
    Florent (confluence_demo_engine). Notifie sur setup en formation (≥ MIN_PILLARS)
    et TOUJOURS quand une position démo s'ouvre. Fail-safe : ne lève jamais.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict
import aiohttp
from utils.config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS, TELEGRAM_MIN_INTERVAL,
    TELEGRAM_SCORE_THRESHOLD, TELEGRAM_SCORE_LABELS, SYMBOLS, SCORE_CRITERIA,
    TELEGRAM_CONFLUENCE_ENABLED, TELEGRAM_CONFLUENCE_MIN_PILLARS,
    TELEGRAM_CONFLUENCE_INTERVAL,
)
from utils.logger import get_logger

logger = get_logger(__name__)
_last_sent: Dict[str, float] = {s: 0.0 for s in SYMBOLS}
_tg_lock = asyncio.Lock()

# ── Canal CONFLUENCE (nouveaux indicateurs) ──────────────────────────────────
_conf_last_sent: Dict[str, float] = {}
_conf_lock = asyncio.Lock()

_PILLARS = [
    ("trend_sr", "Tendance & S/R"), ("fair_value", "Juste-prix"),
    ("liquidity", "Liquidité"), ("ote_ob", "Fib OTE"), ("candle_confirmed", "Bougie"),
]


async def _tg_post(text: str) -> None:
    """Envoi bas niveau à tous les chats. Crée sa propre session. Fail-safe."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    async with aiohttp.ClientSession() as session:
        for chat_id in TELEGRAM_CHAT_IDS:
            try:
                async with session.post(
                    url,
                    json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                          "disable_web_page_preview": True},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as r:
                    if r.status != 200:
                        logger.warning("[TG-CONF] HTTP %s chat=%s: %s", r.status, chat_id,
                                       (await r.text())[:80])
            except Exception as e:  # noqa: BLE001
                logger.error("[TG-CONF] envoi %s: %s", chat_id, e)


def _fmt_price(p) -> str:
    try:
        p = float(p)
    except (TypeError, ValueError):
        return "?"
    return f"{p:,.2f}" if abs(p) >= 100 else f"{p:.5f}"


def _format_confluence(symbol: str, s: Dict[str, Any]) -> str:
    """Message Telegram d'une décision de confluence (5 piliers + preuves)."""
    verdict = s.get("verdict", "BLOCK")
    side = int(s.get("side", 0) or 0)
    fam = (s.get("setup_family") or "").upper() or "—"
    gates = {g.get("name"): g.get("passed") for g in (s.get("gates") or [])}
    npass = sum(1 for k, _ in _PILLARS if gates.get(k))
    placed = s.get("placed") or {}
    is_open = bool(placed.get("sent"))

    aggr = s.get("aggressive") or {}
    dir_txt = "▲ LONG" if side > 0 else ("▼ SHORT" if side < 0 else "— NEUTRE")
    if is_open:
        head = "🚀 <b>POSITION DÉMO OUVERTE</b>"
    elif verdict == "ENTER":
        head = "🟢 <b>ENTRÉE — confluence complète</b>"
    elif aggr.get("ready"):
        head = "⚡ <b>Setup AGRESSIF</b> (structuré, confluence incomplète)"
    else:
        head = "📡 <b>Setup en formation</b>"

    pills = "\n".join(
        f"  {'✅' if gates.get(k) else '⬜'} {lbl}" for k, lbl in _PILLARS)

    tr = s.get("trace") or {}
    pl = tr.get("pillars") or {}
    ev = []
    sr = pl.get("sr") or {}
    if sr.get("on_level_kind"):
        kind = "Support" if sr["on_level_kind"] == "support" else "Résistance"
        ev.append(f"📍 {kind} {_fmt_price(sr.get('on_level'))} (force {sr.get('on_level_strength')})")
    cd = pl.get("candle") or {}
    pats = cd.get("patterns") or []
    if pats:
        arrow = " ▲" if cd.get("direction", 0) > 0 else (" ▼" if cd.get("direction", 0) < 0 else "")
        ev.append(f"🕯 {', '.join(pats)}{arrow}")
    trend = (tr.get("setup") or {}).get("trend_context")
    if trend is None:
        trend = pl.get("trend")
    if trend:
        ev.append(f"📈 Tendance HTF {'haussière ▲' if trend > 0 else 'baissière ▼'}")
    ref = s.get("reference") or {}
    if ref.get("price") is not None:
        dv = ref.get("divergence_pct")
        ev.append(f"⇄ Binance {_fmt_price(ref['price'])} (écart {'+' if (dv or 0) >= 0 else ''}{dv}%)")
    ev_txt = ("\n" + "\n".join(ev)) if ev else ""

    # Plan de trade : point d'entrée, SL, ladder de TP (avec R:R).
    plan = ""
    lv = s.get("levels") or {}
    if lv.get("entry") and lv.get("tps"):
        tp_lines = "\n".join(
            f"  🎯 TP{t.get('n')} : {_fmt_price(t.get('price'))}  ·  R:R {t.get('rr')}"
            for t in lv["tps"])
        plan = (f"\n━━━━━━━━━━━━━━━━━\n<b>Plan de trade</b>\n"
                f"  ⛳ Entrée : {_fmt_price(lv.get('entry'))}\n"
                f"  🛑 SL : {_fmt_price(lv.get('sl'))}  ({lv.get('sl_atr')}×ATR)\n"
                f"{tp_lines}")

    order = ""
    if is_open:
        order = (f"\n━━━━━━━━━━━━━━━━━\n💼 <b>POSITION DÉMO</b> : {placed.get('side','')} "
                 f"lot {placed.get('lot')} @ {_fmt_price(placed.get('price'))}")

    reason = (s.get("reasons") or ["—"])[0]

    return (
        f"{head}\n"
        f"<b>{symbol}</b> {dir_txt} · {fam} · <b>{npass}/5</b> piliers\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"{pills}\n"
        f"{ev_txt}\n"
        f"\n💬 {reason}"
        f"{plan}"
        f"{order}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"<i>Titanium · Confluence · {datetime.now(timezone.utc).strftime('%H:%M UTC')}</i>"
    )


async def send_confluence_alert(symbol: str, s: Dict[str, Any]) -> bool:
    """Alerte Telegram sur une décision de confluence. Envoie si une position s'ouvre
    OU si ≥ MIN_PILLARS piliers s'alignent. Anti-spam par symbole (bypass si position
    ouverte). Ne lève JAMAIS. Retourne True si envoyé."""
    try:
        if not (TELEGRAM_CONFLUENCE_ENABLED and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_IDS):
            return False
        if not isinstance(s, dict) or s.get("verdict") in (None, "ERROR"):
            return False
        gates = {g.get("name"): g.get("passed") for g in (s.get("gates") or [])}
        npass = sum(1 for k, _ in _PILLARS if gates.get(k))
        placed = s.get("placed") or {}
        is_open = bool(placed.get("sent"))

        if not is_open and s.get("verdict") != "ENTER" and npass < TELEGRAM_CONFLUENCE_MIN_PILLARS:
            return False

        now = datetime.now(timezone.utc).timestamp()
        async with _conf_lock:
            last = _conf_last_sent.get(symbol, 0.0)
            if not is_open and (now - last) < TELEGRAM_CONFLUENCE_INTERVAL:
                return False        # anti-spam (sauf position ouverte : priorité absolue)
            _conf_last_sent[symbol] = now

        await _tg_post(_format_confluence(symbol, s))
        logger.info("[TG-CONF] alerte %s %s %d/5%s", symbol, s.get("verdict"), npass,
                    " OUVERTE" if is_open else "")
        return True
    except Exception as e:  # noqa: BLE001 — jamais fatal
        logger.error("[TG-CONF] %s: %s", symbol, e)
        return False


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
