"""api/forex_routes.py — Moteur forex/or MT5 (Axi), paper only.

GET  /forex/status  → stats + connexion MT5
GET  /forex/state   → positions ouvertes, derniers signaux, trades
POST /forex/scan    → force un cycle immédiat
POST /forex/reset   → remet le compte paper forex à zéro
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from api.auth import require_admin

from core.forex_engine import forex_state, get_stats, scan_once, _save
from utils.config import FOREX_CAPITAL, FOREX_ENABLED
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/forex", tags=["forex"])
_ADMIN = [Depends(require_admin)]


@router.get("/status")
async def forex_status() -> JSONResponse:
    from data.mt5_provider import account_snapshot
    import asyncio
    mt5_info = await asyncio.to_thread(account_snapshot)
    return JSONResponse({"enabled": FOREX_ENABLED, "mt5": mt5_info, **get_stats()})


@router.get("/state")
async def forex_full_state() -> JSONResponse:
    return JSONResponse({
        "positions":   forex_state["positions"],
        "last_signal": forex_state["last_signal"],
        "trades":      forex_state["trades"][-30:],
    })


@router.post("/scan", dependencies=_ADMIN)
async def forex_scan() -> JSONResponse:
    if not FOREX_ENABLED:
        raise HTTPException(503, "FOREX_ENABLED=0 — activer dans .env puis redémarrer")
    report = await scan_once()
    return JSONResponse({"status": "ok", **report, **get_stats()})


@router.get("/backtests")
async def forex_backtests() -> JSONResponse:
    """Métriques extraites des rapports natifs MT5 (docs/mt5_reports/*.html)."""
    import re
    from pathlib import Path
    rep_dir = Path(__file__).resolve().parent.parent / "docs" / "mt5_reports"
    out = {}
    for f in sorted(rep_dir.glob("TitaniumV3_*.html")) if rep_dir.exists() else []:
        sym = f.stem.replace("TitaniumV3_", "")
        raw = f.read_bytes()
        h = raw.decode("utf-16") if raw[:2] == b"\xff\xfe" else raw.decode("utf-8", "replace")
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", h, re.S)]

        def val(label):
            for i, c in enumerate(cells):
                if c.startswith(label):
                    return cells[i + 1] if i + 1 < len(cells) else "—"
            return "—"
        out[sym] = {
            "net_pnl":       val("Profit Total Net"),
            "profit_factor": val("Facteur de profit"),
            "winrate":       val("Positions gagnantes (%"),
            "drawdown":      val("Fond Drawdown Maximal"),
            "expectancy":    val("Remboursement attendu"),
            "sharpe":        val("Ratio de Sharpe"),
            "report_url":    f"/forex/backtests/{sym}",
        }
    return JSONResponse({"period": "2023-07 → 2026-07 · H1 · Axi", "reports": out})


@router.get("/backtests/{symbol}")
async def forex_backtest_report(symbol: str):
    """Sert le rapport HTML natif MT5 d'un symbole."""
    from pathlib import Path
    from fastapi.responses import HTMLResponse
    f = (Path(__file__).resolve().parent.parent / "docs" / "mt5_reports"
         / f"TitaniumV3_{symbol}.html")
    if not f.exists():
        raise HTTPException(404, f"Rapport MT5 introuvable pour {symbol}")
    raw = f.read_bytes()
    html = raw.decode("utf-16") if raw[:2] == b"\xff\xfe" else raw.decode("utf-8", "replace")
    return HTMLResponse(html)


@router.get("/optim")
async def forex_optim() -> JSONResponse:
    """Résultats du moteur inversé (tools/asset_optimizer.py) : classement de
    l'univers par potentiel + configs par actif validées en OOS. Lecture seule."""
    import json
    from pathlib import Path
    base = Path(__file__).resolve().parent.parent / "data"
    rep_f, cfg_f = base / "asset_optimizer_report.json", base / "asset_configs.json"
    if not rep_f.exists():
        raise HTTPException(404, "Aucun run d'optimisation — lancer tools/asset_optimizer.py")
    rep = json.loads(rep_f.read_text(encoding="utf-8"))
    cfg = json.loads(cfg_f.read_text(encoding="utf-8")) if cfg_f.exists() else {"assets": {}}
    # classement passe 1 (top 30) aplati pour le dashboard
    ranking = []
    for sym, d in rep.get("pass1", {}).items():
        b = d["best"]; o = b["oos"]
        ranking.append({
            "symbol": sym, "category": d["cost"]["category"].replace("STANDARD_", ""),
            "style": b["style"], "potential": b["potential"],
            "expectancy_bps": o.get("expectancy_bps"), "profit_factor": o.get("profit_factor"),
            "winrate_pct": o.get("winrate_pct"), "trades": o.get("trades"),
            "validated": b.get("validated", False),
        })
    ranking.sort(key=lambda r: r["potential"], reverse=True)
    return JSONResponse({
        "generated": rep.get("generated"), "universe_size": rep.get("universe_size"),
        "validated_count": len(cfg.get("assets", {})),
        "configs": cfg.get("assets", {}), "ranking": ranking[:30],
    })


@router.post("/reset", dependencies=_ADMIN)
async def forex_reset() -> JSONResponse:
    forex_state.update(equity=FOREX_CAPITAL, positions={}, trades=[],
                       last_signal={}, errors=[], scan_count=0)
    _save()
    logger.info("[FOREX] Compte paper forex remis à zéro (%.0f EUR)", FOREX_CAPITAL)
    return JSONResponse({"status": "reset", "equity": FOREX_CAPITAL})
