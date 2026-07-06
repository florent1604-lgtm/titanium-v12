"""indicators/orderbook.py — Analyse institutionnelle du carnet d'ordres L2.

Métriques calculées :
  - Imbalance pondéré bid/ask (par proximité au prix)
  - Murs de liquidité (bid wall / ask wall)
  - Détection d'absorption (mur disparu entre 2 snapshots)
  - Détection de spoofing (apparition/disparition rapide sans exécution)
  - Delta notionnel L2
  - Profondeur ±0.1% du mid price
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from utils.config import (
    ORDERBOOK_IMBALANCE_THRESHOLD, ORDERBOOK_WALL_MULT,
    ORDERBOOK_FUTURES_WEIGHT,
)
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class OrderBookAnalysis:
    """Résultat de l'analyse du carnet d'ordres L2."""
    imbalance_ratio: float = 1.0        # > 1 = bids dominent
    weighted_imbalance: float = 1.0     # pondéré par distance au prix
    wall_detected: bool = False
    wall_side: str = "none"             # 'bid' | 'ask' | 'none'
    wall_price: float = 0.0
    wall_notional_usdt: float = 0.0
    absorption_detected: bool = False
    absorption_side: str = "none"       # 'bid_absorbed' | 'ask_absorbed'
    spoofing_score: float = 0.0         # 0-1, 1 = très suspect
    spread_bps: float = 0.0
    depth_bid_01pct: float = 0.0        # volume bids dans ±0.1%
    depth_ask_01pct: float = 0.0        # volume asks dans ±0.1%
    delta_notional: float = 0.0         # Σbid_notional - Σask_notional
    confirms_side: bool = False

    def to_dict(self) -> dict:
        return {
            "imbalance_ratio": round(self.imbalance_ratio, 3),
            "weighted_imbalance": round(self.weighted_imbalance, 3),
            "wall_detected": self.wall_detected,
            "wall_side": self.wall_side,
            "wall_price": round(self.wall_price, 2),
            "wall_notional_usdt": round(self.wall_notional_usdt, 0),
            "absorption_detected": self.absorption_detected,
            "absorption_side": self.absorption_side,
            "spoofing_score": round(self.spoofing_score, 2),
            "spread_bps": round(self.spread_bps, 2),
            "depth_bid_01pct": round(self.depth_bid_01pct, 2),
            "depth_ask_01pct": round(self.depth_ask_01pct, 2),
            "delta_notional": round(self.delta_notional, 2),
            "confirms_side": self.confirms_side,
        }


def _compute_imbalance(bids, asks, n=50):
    """Ratio brut du volume bid/ask sur les N premiers niveaux."""
    bid_vol = sum(b[1] for b in bids[:n]) if bids else 0
    ask_vol = sum(a[1] for a in asks[:n]) if asks else 0
    total = bid_vol + ask_vol
    if total < 1e-9:
        return 1.0, bid_vol, ask_vol
    return bid_vol / max(ask_vol, 1e-9), bid_vol, ask_vol


def _compute_weighted_imbalance(bids, asks, mid_price, n=50):
    """Imbalance pondéré par la proximité au prix (1/distance²)."""
    if mid_price <= 0:
        return 1.0

    def weighted_sum(levels):
        total = 0.0
        for lvl in levels[:n]:
            price, qty = lvl[0], lvl[1]
            dist = abs(price - mid_price) / mid_price
            weight = 1.0 / max(dist * dist, 1e-10)
            total += qty * weight
        return total

    w_bid = weighted_sum(bids)
    w_ask = weighted_sum(asks)
    return w_bid / max(w_ask, 1e-9)


def _detect_wall(levels, n=50):
    """Détecte un mur de liquidité = niveau avec qty > WALL_MULT × médiane."""
    if not levels or len(levels) < 5:
        return None, 0.0, 0.0
    subset = levels[:n]
    qtys = sorted([lvl[1] for lvl in subset])
    median_qty = qtys[len(qtys) // 2] if qtys else 0
    if median_qty < 1e-9:
        return None, 0.0, 0.0
    threshold = median_qty * ORDERBOOK_WALL_MULT
    for lvl in subset:
        if lvl[1] >= threshold:
            return lvl[0], lvl[1], lvl[0] * lvl[1]
    return None, 0.0, 0.0


def _detect_absorption(history, side):
    """Détecte l'absorption d'un mur entre les 2 derniers snapshots.

    Un mur est "absorbé" si sa taille a diminué de > 80% sans que le prix
    ne l'ait traversé (= ordres exécutés par des institutions).
    """
    if len(history) < 2:
        return False, "none"
    prev = history[-2]
    curr = history[-1]
    prev_key = "f_bids" if side == "bid" else "f_asks"
    curr_key = prev_key

    prev_levels = {lvl[0]: lvl[1] for lvl in prev.get(prev_key, [])}
    curr_levels = {lvl[0]: lvl[1] for lvl in curr.get(curr_key, [])}

    # Chercher un mur dans le snapshot précédent qui a disparu
    if not prev_levels:
        return False, "none"
    prev_qtys = sorted(prev_levels.values())
    median_prev = prev_qtys[len(prev_qtys) // 2] if prev_qtys else 0
    if median_prev < 1e-9:
        return False, "none"
    wall_threshold = median_prev * ORDERBOOK_WALL_MULT

    for price, qty in prev_levels.items():
        if qty >= wall_threshold:
            curr_qty = curr_levels.get(price, 0)
            if curr_qty < qty * 0.2:  # 80%+ absorbé
                absorbed_side = "bid_absorbed" if side == "bid" else "ask_absorbed"
                logger.info("[ORDERBOOK] Absorption détectée @ %.2f (%.2f → %.2f)",
                            price, qty, curr_qty)
                return True, absorbed_side
    return False, "none"


def _detect_spoofing(history, n_snapshots=10):
    """Détecte le spoofing : mur qui apparaît/disparaît > 3× en N snapshots."""
    if len(history) < n_snapshots:
        return 0.0
    # Suivre les niveaux "gros" qui apparaissent et disparaissent
    appearances: Dict[float, int] = {}
    recent = list(history)[-n_snapshots:]

    for snap in recent:
        for key in ("f_bids", "f_asks"):
            levels = snap.get(key, [])
            if not levels:
                continue
            qtys = [l[1] for l in levels]
            if not qtys:
                continue
            median_q = sorted(qtys)[len(qtys) // 2]
            threshold = median_q * ORDERBOOK_WALL_MULT
            for lvl in levels:
                if lvl[1] >= threshold:
                    appearances[lvl[0]] = appearances.get(lvl[0], 0) + 1

    if not appearances:
        return 0.0

    # Un niveau qui apparaît dans certains snapshots mais pas tous = suspect
    max_appearances = max(appearances.values())
    if max_appearances >= 3 and max_appearances < n_snapshots * 0.7:
        return min(1.0, max_appearances / n_snapshots)
    return 0.0


def _compute_depth_around(levels, mid_price, pct=0.001):
    """Volume total dans ±pct% du mid price."""
    if not levels or mid_price <= 0:
        return 0.0
    low = mid_price * (1 - pct)
    high = mid_price * (1 + pct)
    return sum(lvl[1] * lvl[0] for lvl in levels if low <= lvl[0] <= high)


def analyze_orderbook_l2(state, side: str) -> Optional[OrderBookAnalysis]:
    """Analyse complète du carnet d'ordres L2.

    Combine le carnet spot ET futures pour une vue institutionnelle.
    Le carnet futures est pondéré ORDERBOOK_FUTURES_WEIGHT× car c'est là
    que les institutions placent leurs ordres.

    Args:
        state: OrderBookState depuis orderbook_ws.orderbook_store
        side: 'ACHAT' ou 'VENTE' depuis le scoring engine

    Returns:
        OrderBookAnalysis avec toutes les métriques
    """
    if state is None:
        return None

    result = OrderBookAnalysis()
    result.spread_bps = state.spread_bps
    mid = state.mid_price

    # Combiner spot + futures (futures pondéré 2×)
    fw = ORDERBOOK_FUTURES_WEIGHT
    combined_bids = list(state.bids)
    combined_asks = list(state.asks)
    for fb in state.futures_bids:
        combined_bids.append([fb[0], fb[1] * fw])
    for fa in state.futures_asks:
        combined_asks.append([fa[0], fa[1] * fw])
    combined_bids.sort(key=lambda x: x[0], reverse=True)
    combined_asks.sort(key=lambda x: x[0])

    # 1. Imbalance
    ratio, bid_vol, ask_vol = _compute_imbalance(combined_bids, combined_asks, 50)
    result.imbalance_ratio = ratio

    # 2. Weighted imbalance
    result.weighted_imbalance = _compute_weighted_imbalance(
        combined_bids, combined_asks, mid, 50
    )

    # 3. Wall detection
    bid_wall_price, bid_wall_qty, bid_wall_not = _detect_wall(combined_bids, 50)
    ask_wall_price, ask_wall_qty, ask_wall_not = _detect_wall(combined_asks, 50)

    if bid_wall_price and ask_wall_price:
        if bid_wall_not > ask_wall_not:
            result.wall_detected = True
            result.wall_side = "bid"
            result.wall_price = bid_wall_price
            result.wall_notional_usdt = bid_wall_not
        else:
            result.wall_detected = True
            result.wall_side = "ask"
            result.wall_price = ask_wall_price
            result.wall_notional_usdt = ask_wall_not
    elif bid_wall_price:
        result.wall_detected = True
        result.wall_side = "bid"
        result.wall_price = bid_wall_price
        result.wall_notional_usdt = bid_wall_not
    elif ask_wall_price:
        result.wall_detected = True
        result.wall_side = "ask"
        result.wall_price = ask_wall_price
        result.wall_notional_usdt = ask_wall_not

    # 4. Absorption detection
    if state.history:
        abs_bid, abs_bid_side = _detect_absorption(state.history, "bid")
        abs_ask, abs_ask_side = _detect_absorption(state.history, "ask")
        if abs_bid:
            result.absorption_detected = True
            result.absorption_side = abs_bid_side
        elif abs_ask:
            result.absorption_detected = True
            result.absorption_side = abs_ask_side

    # 5. Spoofing
    if state.history:
        result.spoofing_score = _detect_spoofing(state.history)

    # 6. Depth ±0.1%
    result.depth_bid_01pct = _compute_depth_around(combined_bids, mid)
    result.depth_ask_01pct = _compute_depth_around(combined_asks, mid)

    # 7. Delta notionnel
    bid_notional = sum(b[0] * b[1] for b in combined_bids[:50])
    ask_notional = sum(a[0] * a[1] for a in combined_asks[:50])
    result.delta_notional = bid_notional - ask_notional

    # 8. Confirmation du side SMC
    imb_threshold = ORDERBOOK_IMBALANCE_THRESHOLD
    if side == "ACHAT":
        result.confirms_side = (
            result.weighted_imbalance > imb_threshold
            or (result.wall_detected and result.wall_side == "bid")
            or (result.absorption_detected and result.absorption_side == "ask_absorbed")
        )
    elif side == "VENTE":
        result.confirms_side = (
            result.weighted_imbalance < (1.0 / imb_threshold)
            or (result.wall_detected and result.wall_side == "ask")
            or (result.absorption_detected and result.absorption_side == "bid_absorbed")
        )

    # Annuler si spoofing détecté
    if result.spoofing_score > 0.7:
        result.confirms_side = False

    return result
