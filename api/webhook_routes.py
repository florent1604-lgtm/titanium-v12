"""api/webhook_routes.py — Endpoint webhook TradingView pour Titanium v12.

Reçoit les alertes TradingView, les valide, les filtre via Fundamentals
et les exécute via le Paper Executor.

Payload JSON attendu dans le champ "Message" de l'alerte TradingView :
{
  "secret":   "ton_secret_partagé",     // Requis si WEBHOOK_SECRET configuré
  "ticker":   "{{ticker}}",              // Ex: "BTCUSDT"
  "action":   "{{strategy.order.action}}", // "buy" | "sell" | "long" | "short"
  "price":    {{close}},
  "score":    8,                         // Optionnel — score estimé (1-11)
  "strategy": "SMC_v12",                // Optionnel
  "sl":       0,                         // Optionnel — calculé si 0
  "tp1":      0, "tp2": 0, "tp3": 0,
  "comment":  "BOS + OB/FVG alignment"  // Optionnel
}
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi import Request as FARequest
from fastapi.responses import JSONResponse

from utils.config import (
    SYMBOLS, TRADING_MODE, WEBHOOK_ENABLED, WEBHOOK_SECRET,
)
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhook"])

# Déduplication : évite de rejouer le même signal 2× en moins de 5s
_recent: Dict[str, float] = {}
_DEDUP_SEC = 5.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize_symbol(raw: str) -> str:
    """Convertit un ticker TradingView en symbole interne (ex: BTCUSDT → BTC/USDT)."""
    raw = raw.upper().strip().replace(".", "").replace("-", "")
    # Correspondance directe
    for sym in SYMBOLS:
        if raw == sym.replace("/", ""):
            return sym
    # Tentative XXXUSDT → XXX/USDT
    if raw.endswith("USDT"):
        candidate = raw[:-4] + "/USDT"
        if candidate in SYMBOLS:
            return candidate
    return raw  # retourné tel quel — sera rejeté plus bas si non suivi


def _validate_secret(payload: Dict[str, Any]) -> None:
    # Fail-closed (revue Codex 10/07/2026) : un webhook peut ouvrir une position,
    # donc un secret VIDE doit tout refuser (avant : secret vide = tout accepté).
    import secrets as _secrets
    if not WEBHOOK_SECRET:
        raise HTTPException(403, "Webhook refusé : WEBHOOK_SECRET non configuré côté serveur.")
    provided = str(payload.get("secret") or "")
    if not _secrets.compare_digest(provided, str(WEBHOOK_SECRET)):
        raise HTTPException(401, "Secret invalide")


def _parse_action(payload: Dict[str, Any]) -> str:
    """Retourne 'ACHAT' ou 'VENTE'."""
    raw = str(payload.get("action") or payload.get("side") or "").lower()
    if raw in ("buy", "long", "achat"):
        return "ACHAT"
    if raw in ("sell", "short", "vente"):
        return "VENTE"
    raise HTTPException(422, f"Action invalide: {raw!r} — attendu buy/sell/long/short")


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/tradingview")
async def tradingview_webhook(request: FARequest):
    """Reçoit une alerte TradingView et l'exécute en paper trading.

    Flux :
      1. Validation (secret, action, symbole)
      2. Déduplication (5s fenêtre)
      3. Calcul SL/TP si manquants (via risk manager + candle store)
      4. Filtrage Fundamentals (si module actif)
      5. Exécution via executor.execute()
    """
    if not WEBHOOK_ENABLED:
        raise HTTPException(503, "Webhook désactivé (WEBHOOK_ENABLED=0)")

    # Parse JSON
    try:
        payload: Dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(400, "Body JSON invalide")

    # Validation secrète
    _validate_secret(payload)

    # Symbole
    raw_ticker = str(payload.get("ticker") or payload.get("symbol") or "")
    sym = _normalize_symbol(raw_ticker)
    if sym not in SYMBOLS:
        return JSONResponse({
            "status":  "ignored",
            "reason":  f"Symbole {raw_ticker!r} non suivi — actifs: {SYMBOLS}",
            "sym_normalized": sym,
        })

    # Action
    side = _parse_action(payload)

    # Prix
    price_raw = payload.get("price") or payload.get("close")
    if price_raw is None:
        raise HTTPException(422, "Prix manquant (champ 'price' ou 'close')")
    price = float(price_raw)
    if price <= 0:
        raise HTTPException(422, f"Prix invalide: {price}")

    # Déduplication
    dedup_key = f"{sym}:{side}"
    now = time.monotonic()
    if now - _recent.get(dedup_key, 0.0) < _DEDUP_SEC:
        return JSONResponse({"status": "ignored", "reason": "Doublon détecté (fenêtre 5s)"})
    _recent[dedup_key] = now

    # SL/TP fournis ou à calculer
    sl  = float(payload.get("sl",  0))
    tp1 = float(payload.get("tp1", 0))
    tp2 = float(payload.get("tp2", 0))
    tp3 = float(payload.get("tp3", 0))
    atr = 0.0

    if sl <= 0 or tp1 <= 0:
        try:
            from data.binance_ws import candle_store
            from execution.risk_manager import compute_adaptive_levels
            df = candle_store.get(sym)
            if df is not None and len(df) >= 14:
                levels = compute_adaptive_levels(df, sym, side, price)
                sl  = float(levels.get("sl",  0))
                tp1 = float(levels.get("tp1", 0))
                tp2 = float(levels.get("tp2", 0))
                tp3 = float(levels.get("tp3", 0))
                atr = float(levels.get("atr", 0))
                logger.info(
                    "[WEBHOOK] SL/TP calculés pour %s %s — sl=%.4f tp1=%.4f",
                    sym, side, sl, tp1,
                )
            else:
                logger.warning("[WEBHOOK] Candles insuffisantes pour %s — SL/TP non calculés", sym)
        except Exception as e:
            logger.warning("[WEBHOOK] Calcul SL/TP: %s", e)

    # Construire le signal interne
    signal: Dict[str, Any] = {
        "symbol":         sym,
        "side":           side,
        "price":          price,
        "sl":             sl,
        "tp1":            tp1,
        "tp2":            tp2,
        "tp3":            tp3,
        "atr":            atr,
        "score":          int(payload.get("score", 7)),
        "active":         True,
        "correlation_id": f"tv_{int(time.time() * 1000) % 1_000_000_000}",
        "source":         "tradingview",
        "strategy":       str(payload.get("strategy", "external")),
        "comment":        str(payload.get("comment", "")),
        "ts":             datetime.now(timezone.utc).isoformat(),
    }

    # ── Filtrage Fundamentals ─────────────────────────────────────────────────
    if TRADING_MODE in ("paper", "live"):
        try:
            from fundamentals.signal_modulator import is_active, modulate
            from fundamentals.risk_scorer import get_current_score
            if is_active():
                risk_score = get_current_score()
                modulated = modulate(signal, risk_score)
                if modulated is None:
                    logger.info(
                        "[WEBHOOK] %s %s bloqué par Fundamentals (risk=%.1f)",
                        sym, side, risk_score,
                    )
                    return JSONResponse({
                        "status":     "filtered",
                        "reason":     "Bloqué par Fundamentals (risque macro élevé)",
                        "risk_score": risk_score,
                    })
                signal = modulated
        except Exception as e:
            logger.warning("[WEBHOOK] Filtrage Fundamentals: %s", e)

    # ── Exécution ──────────────────────────────────────────────────────────────
    result = None
    if TRADING_MODE in ("paper", "live"):
        try:
            from execution.executor import executor
            result = await executor.execute(signal)
        except Exception as e:
            logger.error("[WEBHOOK] Erreur exécution: %s", e)

    status = "accepted" if result else "rejected"
    logger.info(
        "[WEBHOOK] TradingView → %s %s prix=%.4f | %s | score=%d",
        sym, side, price, status, signal.get("score", 0),
    )

    return JSONResponse({
        "status":   status,
        "symbol":   sym,
        "side":     side,
        "price":    price,
        "score":    signal.get("score"),
        "sl":       sl,
        "tp1":      tp1,
        "position": result,
    })


# ── GET /webhook/status ───────────────────────────────────────────────────────

@router.get("/status")
async def webhook_status():
    """Vérifie que le webhook est actif et correctement configuré."""
    return JSONResponse({
        "enabled":         WEBHOOK_ENABLED,
        "secret_set":      bool(WEBHOOK_SECRET),
        "trading_mode":    TRADING_MODE,
        "tracked_symbols": SYMBOLS,
        "dedup_window_sec": _DEDUP_SEC,
    })


# ── GET /webhook/positions-for-tv ─────────────────────────────────────────────

@router.get("/positions-for-tv")
async def positions_for_tv():
    """Retourne les positions paper formatées pour TradingView.

    Usage :
      1. Copier le code Pine Script retourné dans un nouvel indicateur TradingView
      2. Les positions s'afficheront comme des lignes SL/TP sur le graphique
      3. Ou utiliser le tableau JSON pour votre propre visualisation

    Astuce : recharger cette page toutes les minutes via une URL d'alerte TradingView
    ou un script externe pour garder les annotations à jour.
    """
    if TRADING_MODE == "disabled":
        return JSONResponse({"positions": [], "pine_script": "// Mode disabled"})

    from execution.executor import executor
    state = executor.get_state()
    positions = state.get("positions", {})

    # ── Données brutes JSON ────────────────────────────────────────────────────
    pos_list = []
    for sym, pos in positions.items():
        pos_list.append({
            "symbol":      sym,
            "side":        pos.get("side"),
            "entry":       pos.get("entry_price"),
            "sl":          pos.get("sl"),
            "tp1":         pos.get("tp1"),
            "tp2":         pos.get("tp2"),
            "tp3":         pos.get("tp3"),
            "size_usdt":   pos.get("size_usdt"),
            "remaining":   pos.get("remaining_pct", 1.0),
            "unrealized_pnl": pos.get("unrealized_pnl"),
            "score":       pos.get("score"),
            "entry_ts":    pos.get("entry_ts"),
        })

    # ── Génération du Pine Script v5 ───────────────────────────────────────────
    if not pos_list:
        pine = _pine_no_positions()
    else:
        pine = _pine_with_positions(pos_list)

    return JSONResponse({
        "positions":   pos_list,
        "count":       len(pos_list),
        "pine_script": pine,
        "instructions": (
            "1. Ouvrir TradingView → Pine Editor → Nouveau script\n"
            "2. Coller le pine_script retourné\n"
            "3. Ajouter au graphique → les positions apparaissent en overlay\n"
            "4. Recharger ce endpoint pour mettre à jour (pas de mise à jour auto)"
        ),
    })


def _pine_no_positions() -> str:
    return """//@version=5
indicator("Titanium Paper Positions", overlay=true)
label.new(bar_index, high, "⬡ Aucune position paper ouverte",
    color=color.new(color.gray, 80), textcolor=color.gray, size=size.small)
"""


def _pine_escape(s: str) -> str:
    """Échappe les guillemets et caractères dangereux pour l'inclusion dans du code Pine Script."""
    # Supprimer tout ce qui n'est pas alphanumérique, espace, +, -, ., $, %
    import re
    return re.sub(r'[^a-zA-Z0-9 \+\-\.\$\%\_\/]', '', str(s))[:40]


def _pine_with_positions(positions: list) -> str:
    """Génère un script Pine v5 qui affiche les positions paper sur le graphique."""
    lines = ['//@version=5', 'indicator("Titanium Paper Positions", overlay=true)', '']

    for i, pos in enumerate(positions):
        # Valeurs numériques uniquement — pas d'interpolation chaîne pour les prix
        sym   = _pine_escape(pos["symbol"].replace("/", "").replace("USDT", ""))
        side  = "LONG" if str(pos.get("side", "")).upper() in ("LONG", "ACHAT") else "SHORT"
        entry = float(pos.get("entry") or 0)
        sl    = float(pos.get("sl") or 0)
        tp1   = float(pos.get("tp1") or 0)
        tp2   = float(pos.get("tp2") or 0)
        tp3   = float(pos.get("tp3") or 0)
        pnl   = float(pos.get("unrealized_pnl") or 0)
        color = "color.green" if side == "LONG" else "color.red"
        pnl_str = _pine_escape(f"{pnl:+.2f}$") if pnl else ""

        lines += [
            f"// Position {i+1}: {sym} {side}",
            f"entry_{i} = {entry:.4f}",
            f"sl_{i}    = {sl:.4f}",
            f"tp1_{i}   = {tp1:.4f}",
            f"tp2_{i}   = {tp2:.4f}",
            f"tp3_{i}   = {tp3:.4f}",
            f'label.new(bar_index, entry_{i}, "{sym} {side} {pnl_str}",',
            f'    color={color}, textcolor=color.white, size=size.small, style=label.style_label_right)',
            f"line.new(bar_index - 5, entry_{i}, bar_index, entry_{i}, color={color}, width=2)",
        ]
        if sl > 0:
            lines += [
                f"line.new(bar_index - 5, sl_{i}, bar_index, sl_{i}, "
                f"color=color.red, style=line.style_dashed, width=1)",
                f'label.new(bar_index, sl_{i}, "SL {sl:.2f}", color=color.new(color.red, 70), '
                f"textcolor=color.red, size=size.tiny)",
            ]
        for tp_var, tp_val, tp_label in [
            (f"tp1_{i}", tp1, "TP1"), (f"tp2_{i}", tp2, "TP2"), (f"tp3_{i}", tp3, "TP3")
        ]:
            if tp_val > 0:
                lines += [
                    f"line.new(bar_index - 5, {tp_var}, bar_index, {tp_var}, "
                    f"color=color.new(color.green, 50), style=line.style_dotted, width=1)",
                    f'label.new(bar_index, {tp_var}, "{tp_label} {tp_val:.2f}", '
                    f"color=color.new(color.green, 70), textcolor=color.green, size=size.tiny)",
                ]
        lines.append('')

    return '\n'.join(lines)
