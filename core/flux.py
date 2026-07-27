"""core/flux.py — STORE DE FLUX AFFÉRENT CONTINU (socle N0). Réorg (Florent 27/07).

« Alimenter en continu les différents flux (fondamentaux, coût, exposition…) et tous les
organes du bot. » Ce store expose chaque flux via un getter à CACHE TTL : la valeur est
rafraîchie PARESSEUSEMENT depuis sa source dès qu'elle est périmée — pas de boucle dédiée,
pas de martelage. Plusieurs organes (state_builder → SystemState → RiskGate, /health, N6…)
lisent la MÊME valeur fraîche.

FAIL-SAFE : source indisponible → on rend la dernière valeur connue, sinon un défaut NEUTRE
(jamais une exception, jamais un blocage). Imports métier PARESSEUX (invariant #6).
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional


class _TTLCache:
    """Cache clé→(valeur, expiration) thread-safe avec rafraîchissement paresseux."""
    def __init__(self):
        self._d: Dict[str, tuple] = {}
        self._lock = threading.Lock()

    def get(self, key: str, ttl: float, producer: Callable[[], Any], default: Any = None) -> Any:
        now = time.monotonic()
        with self._lock:
            hit = self._d.get(key)
            if hit and hit[1] > now:
                return hit[0]
            last = hit[0] if hit else default
        try:
            val = producer()
            if val is None:
                val = last
        except Exception:
            val = last                                   # fail-safe : dernière valeur connue
        with self._lock:
            self._d[key] = (val, now + ttl)
        return val


_cache = _TTLCache()


# ── Fondamentaux (macro 0-100 → block/reduce) ────────────────────────────────
def fundamentals(ttl: float = 300.0) -> Dict[str, Any]:
    def _p():
        from poles.fundamentals.risk_scorer import get_current_score
        try:
            from utils.config import FUNDAMENTALS_RISK_BLOCK, FUNDAMENTALS_RISK_REDUCE
            blk, red = float(FUNDAMENTALS_RISK_BLOCK), float(FUNDAMENTALS_RISK_REDUCE)
        except Exception:
            blk, red = 70.0, 30.0
        score = float(get_current_score())
        return {"risk_score": round(score, 1),
                "level": "high" if score >= blk else ("medium" if score >= red else "low"),
                "would_block": score >= blk, "would_reduce": red <= score < blk}
    return _cache.get("fundamentals", ttl, _p,
                      default={"risk_score": None, "level": None,
                               "would_block": False, "would_reduce": False})


# ── Exposition portefeuille (gross/net %) ────────────────────────────────────
def exposure(ttl: float = 20.0) -> Dict[str, Any]:
    def _p():
        from core.portfolio_risk import exposure_snapshot
        snap = exposure_snapshot() or {}
        eq = ((snap.get("equity_live_eur") or {}).get("total")) or 0.0
        gross_eur = float(snap.get("gross_eur") or 0.0)
        net_eur = float(snap.get("net_eur") or 0.0)
        gp = round(gross_eur / eq * 100.0, 2) if eq else None
        npct = round(net_eur / eq * 100.0, 2) if eq else None
        return {"gross_pct": gp, "net_pct": npct, "gross_eur": gross_eur, "net_eur": net_eur}
    return _cache.get("exposure", ttl, _p, default={"gross_pct": None, "net_pct": None})


# ── Compte démo (equity/balance) ─────────────────────────────────────────────
def account(ttl: float = 10.0) -> Dict[str, Any]:
    def _p():
        import MetaTrader5 as mt5
        from ingestion.market.mt5_provider import ensure_init, mt5_lock
        if not ensure_init():
            return None
        with mt5_lock:
            a = mt5.account_info()
        if a is None:
            return None
        return {"login": a.login, "equity": round(a.equity, 2),
                "balance": round(a.balance, 2), "floating": round(a.profit, 2)}
    return _cache.get("account", ttl, _p, default={"equity": None, "balance": None})


# ── Coût aller-retour par actif (distance de prix) ───────────────────────────
def roundtrip_cost(symbol: str, price: Optional[float], ttl: float = 5.0) -> Optional[float]:
    """Coût aller-retour estimé en UNITÉS DE PRIX (2×spread) — pour le filtre de coût du
    RiskGate. Depuis le tick MT5 (spread live), fail-safe."""
    if not symbol or not price:
        return None
    def _p():
        import MetaTrader5 as mt5
        from ingestion.market.mt5_provider import ensure_init, mt5_lock
        if not ensure_init():
            return None
        with mt5_lock:
            tick = mt5.symbol_info_tick(symbol)
        if not tick or not tick.ask or not tick.bid:
            return None
        return float(tick.ask - tick.bid) * 2.0          # aller-retour ≈ 2× spread
    return _cache.get(f"cost:{symbol}", ttl, _p, default=None)


# ── Contexte MACRO / sentiment (fear&greed, marché global) ───────────────────
def market_context(ttl: float = 120.0) -> Dict[str, Any]:
    def _p():
        from poles.fundamentals.external_feeds import get_external_snapshot
        snap = get_external_snapshot() or {}
        fg = (snap.get("fear_greed") or {})
        return {"fear_greed": fg.get("value") or fg.get("score"),
                "fear_greed_label": fg.get("label") or fg.get("classification"),
                "global_market": snap.get("global_market")}
    return _cache.get("market_context", ttl, _p, default={"fear_greed": None})


# ── NEWS / journaux mondiaux (dernières manchettes) ──────────────────────────
def news_headlines(limit: int = 8, ttl: float = 120.0) -> list:
    """Dernières manchettes (RSS/NewsAPI/GDELT, cache de la boucle fundamentals). Pour le
    contexte de prise de position ET la base RAG de Cloe. Fail-safe → []."""
    def _p():
        from poles.fundamentals.fetcher_loop import get_cached_articles
        arts = get_cached_articles() or []
        out = []
        for a in arts[:limit]:
            out.append({"title": a.get("title"), "source": a.get("source") or a.get("feed"),
                        "published": a.get("published") or a.get("time")})
        return out
    return _cache.get("news", ttl, _p, default=[]) or []


def snapshot() -> Dict[str, Any]:
    """Vue compacte de tous les flux (pour /health et debug)."""
    return {"fundamentals": fundamentals(), "exposure": exposure(), "account": account(),
            "market_context": market_context(), "news_count": len(news_headlines())}
