"""tests/test_orderbook_l2.py — Tests unitaires Order Book L2 + spread + drawdown."""
from __future__ import annotations
import asyncio
import sys
import os
import time
from collections import deque
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _make_ob_state(bid_prices=None, ask_prices=None, f_bid_prices=None, f_ask_prices=None):
    """Crée un OrderBookState synthétique pour les tests."""
    from data.orderbook_ws import OrderBookState
    state = OrderBookState()
    if bid_prices:
        state.bids = [[p, q] for p, q in bid_prices]
    if ask_prices:
        state.asks = [[p, q] for p, q in ask_prices]
    if f_bid_prices:
        state.futures_bids = [[p, q] for p, q in f_bid_prices]
    if f_ask_prices:
        state.futures_asks = [[p, q] for p, q in f_ask_prices]
    state._compute_derived()
    state.ts = time.time()
    return state


# ── Test OrderBookState ──────────────────────────────────────────────────────

class TestOrderBookState:
    def test_compute_derived_basic(self):
        state = _make_ob_state(
            bid_prices=[(100.0, 5.0), (99.0, 3.0)],
            ask_prices=[(101.0, 4.0), (102.0, 2.0)],
        )
        assert state.best_bid == 100.0
        assert state.best_ask == 101.0
        assert state.mid_price == 100.5
        assert state.spread_bps > 0
        # Spread = (101 - 100) / 100.5 * 10000 ≈ 99.5 bps
        assert 95 < state.spread_bps < 105

    def test_compute_derived_futures_fallback(self):
        """Si pas de spot, utilise futures pour le spread."""
        state = _make_ob_state(
            f_bid_prices=[(50000.0, 1.0), (49990.0, 2.0)],
            f_ask_prices=[(50010.0, 1.0), (50020.0, 2.0)],
        )
        assert state.best_bid == 50000.0
        assert state.best_ask == 50010.0
        assert state.mid_price == 50005.0
        assert state.spread_bps > 0

    def test_push_history(self):
        state = _make_ob_state(
            bid_prices=[(100.0, 5.0)],
            ask_prices=[(101.0, 4.0)],
            f_bid_prices=[(100.0, 10.0)],
            f_ask_prices=[(101.0, 8.0)],
        )
        state.push_history()
        assert len(state.history) == 1
        snap = state.history[0]
        assert "ts" in snap
        assert len(snap["bids"]) == 1
        assert len(snap["f_bids"]) == 1

    def test_to_dict(self):
        state = _make_ob_state(
            bid_prices=[(100.0, 5.0)],
            ask_prices=[(101.0, 4.0)],
        )
        d = state.to_dict()
        assert "best_bid" in d
        assert "spread_bps" in d
        assert "spot_levels" in d


# ── Test Orderbook Analysis ──────────────────────────────────────────────────

class TestOrderbookAnalysis:
    def test_imbalance_bullish(self):
        """Bids >> Asks → ratio > 1 → bullish."""
        from indicators.orderbook import analyze_orderbook_l2
        state = _make_ob_state(
            bid_prices=[(100.0 - i * 0.1, 10.0) for i in range(20)],
            ask_prices=[(100.1 + i * 0.1, 2.0) for i in range(20)],
        )
        result = analyze_orderbook_l2(state, "ACHAT")
        assert result is not None
        assert result.imbalance_ratio > 1.5
        assert result.confirms_side is True

    def test_imbalance_bearish(self):
        """Asks >> Bids → ratio < 1 → bearish."""
        from indicators.orderbook import analyze_orderbook_l2
        state = _make_ob_state(
            bid_prices=[(100.0 - i * 0.1, 2.0) for i in range(20)],
            ask_prices=[(100.1 + i * 0.1, 10.0) for i in range(20)],
        )
        result = analyze_orderbook_l2(state, "VENTE")
        assert result is not None
        assert result.imbalance_ratio < 0.67
        assert result.confirms_side is True

    def test_wall_detection_bid(self):
        """Un niveau bid avec volume 10× la médiane → mur détecté."""
        from indicators.orderbook import analyze_orderbook_l2
        bids = [(100.0 - i * 0.1, 1.0) for i in range(20)]
        bids[5] = (bids[5][0], 50.0)  # mur à l'index 5
        state = _make_ob_state(
            bid_prices=bids,
            ask_prices=[(100.1 + i * 0.1, 1.0) for i in range(20)],
        )
        result = analyze_orderbook_l2(state, "ACHAT")
        assert result is not None
        assert result.wall_detected is True
        assert result.wall_side == "bid"
        assert result.wall_notional_usdt > 0

    def test_wall_detection_ask(self):
        """Un niveau ask avec volume 10× la médiane → mur détecté."""
        from indicators.orderbook import analyze_orderbook_l2
        asks = [(100.1 + i * 0.1, 1.0) for i in range(20)]
        asks[3] = (asks[3][0], 50.0)  # mur à l'index 3
        state = _make_ob_state(
            bid_prices=[(100.0 - i * 0.1, 1.0) for i in range(20)],
            ask_prices=asks,
        )
        result = analyze_orderbook_l2(state, "VENTE")
        assert result is not None
        assert result.wall_detected is True
        assert result.wall_side == "ask"

    def test_no_wall_uniform(self):
        """Pas de mur si tous les niveaux ont le même volume."""
        from indicators.orderbook import analyze_orderbook_l2
        state = _make_ob_state(
            bid_prices=[(100.0 - i * 0.1, 5.0) for i in range(20)],
            ask_prices=[(100.1 + i * 0.1, 5.0) for i in range(20)],
        )
        result = analyze_orderbook_l2(state, "ACHAT")
        assert result is not None
        assert result.wall_detected is False

    def test_absorption_detection(self):
        """Mur disparu entre 2 snapshots → absorption détectée."""
        from indicators.orderbook import analyze_orderbook_l2
        state = _make_ob_state(
            f_bid_prices=[(50000.0 - i * 10, 1.0) for i in range(20)],
            f_ask_prices=[(50010.0 + i * 10, 1.0) for i in range(20)],
        )
        # Snapshot 1 : gros mur bid
        f_bids_prev = [(50000.0 - i * 10, 1.0) for i in range(20)]
        f_bids_prev[3] = (f_bids_prev[3][0], 100.0)  # mur
        state.history.append({
            "ts": time.time() - 5,
            "bids": [], "asks": [],
            "f_bids": [list(b) for b in f_bids_prev],
            "f_asks": [[50010.0 + i * 10, 1.0] for i in range(20)],
        })
        # Snapshot 2 : mur disparu
        state.history.append({
            "ts": time.time(),
            "bids": [], "asks": [],
            "f_bids": [[50000.0 - i * 10, 1.0] for i in range(20)],
            "f_asks": [[50010.0 + i * 10, 1.0] for i in range(20)],
        })
        result = analyze_orderbook_l2(state, "ACHAT")
        assert result is not None
        assert result.absorption_detected is True

    def test_none_state_returns_none(self):
        from indicators.orderbook import analyze_orderbook_l2
        assert analyze_orderbook_l2(None, "ACHAT") is None

    def test_to_dict(self):
        from indicators.orderbook import analyze_orderbook_l2
        state = _make_ob_state(
            bid_prices=[(100.0, 5.0)],
            ask_prices=[(101.0, 4.0)],
        )
        result = analyze_orderbook_l2(state, "ACHAT")
        d = result.to_dict()
        assert "imbalance_ratio" in d
        assert "wall_detected" in d
        assert "confirms_side" in d

    def test_futures_weighted_more(self):
        """Les futures sont pondérés 2× dans l'imbalance combiné."""
        from indicators.orderbook import analyze_orderbook_l2
        # Spot balanced, futures heavily bid-sided
        state = _make_ob_state(
            bid_prices=[(100.0, 5.0)],
            ask_prices=[(101.0, 5.0)],
            f_bid_prices=[(100.0, 20.0)],
            f_ask_prices=[(101.0, 2.0)],
        )
        result = analyze_orderbook_l2(state, "ACHAT")
        assert result is not None
        # With futures weighted 2×, bids should dominate
        assert result.imbalance_ratio > 1.5


# ── Test Spread Tracker ──────────────────────────────────────────────────────

class TestSpreadTracker:
    def test_initial_fallback(self):
        from data.spread_tracker import SpreadTracker
        tracker = SpreadTracker()
        # No data yet → fallback to static
        spread = tracker.get_spread_bps("BTC/USDT")
        assert spread > 0

    def test_update_and_get(self):
        from data.spread_tracker import SpreadTracker
        tracker = SpreadTracker()
        tracker.update("BTC/USDT", 1.5)
        tracker.update("BTC/USDT", 2.0)
        tracker.update("BTC/USDT", 1.8)
        spread = tracker.get_spread_bps("BTC/USDT")
        assert 0 < spread < 10

    def test_effective_spread_small_order(self):
        from data.spread_tracker import SpreadTracker
        tracker = SpreadTracker()
        tracker.update("BTC/USDT", 2.0)
        small = tracker.get_effective_spread("BTC/USDT", 100)
        large = tracker.get_effective_spread("BTC/USDT", 10000)
        assert large > small  # market impact

    def test_stats(self):
        from data.spread_tracker import SpreadTracker
        tracker = SpreadTracker()
        tracker.update("BTC/USDT", 1.5)
        tracker.update("BTC/USDT", 2.5)
        stats = tracker.get_stats("BTC/USDT")
        assert stats["source"] == "realtime"
        assert stats["samples"] == 2


# ── Test Scoring Integration /16 ────────────────────────────────────────────

class TestScoringIntegration:
    def test_score_max_is_16(self):
        from utils.config import SCORE_CRITERIA
        assert len(SCORE_CRITERIA) == 16
        assert "ORDERBOOK_IMBALANCE" in SCORE_CRITERIA
        assert "ORDERBOOK_WALL" in SCORE_CRITERIA

    def test_score_min_required(self):
        from utils.config import SCORE_MIN_REQUIRED
        assert SCORE_MIN_REQUIRED == 8


# ── Test Depth Update ────────────────────────────────────────────────────────

class TestDepthUpdate:
    def test_apply_depth_update_add(self):
        from data.orderbook_ws import _apply_depth_update, _book_map
        carnet = _book_map([[100.0, 5.0], [99.0, 3.0]])
        updates = [[98.0, 2.0]]
        result = _apply_depth_update(carnet, updates, is_bids=True)
        assert len(result) == 3
        assert result[0][0] == 100.0  # sorted desc

    def test_apply_depth_update_remove(self):
        from data.orderbook_ws import _apply_depth_update, _book_map
        carnet = _book_map([[100.0, 5.0], [99.0, 3.0]])
        updates = [[99.0, 0]]  # qty=0 → remove
        result = _apply_depth_update(carnet, updates, is_bids=True)
        assert len(result) == 1
        assert result[0][0] == 100.0

    def test_apply_depth_update_replace(self):
        from data.orderbook_ws import _apply_depth_update, _book_map
        carnet = _book_map([[100.0, 5.0], [99.0, 3.0]])
        updates = [[100.0, 10.0]]  # update qty
        result = _apply_depth_update(carnet, updates, is_bids=True)
        assert len(result) == 2
        assert result[0][1] == 10.0

    def test_asks_sorted_ascending(self):
        from data.orderbook_ws import _apply_depth_update, _book_map
        carnet = _book_map([[101.0, 5.0], [102.0, 3.0]])
        updates = [[100.5, 2.0]]
        result = _apply_depth_update(carnet, updates, is_bids=False)
        assert result[0][0] == 100.5  # sorted asc

    def test_carnet_mute_en_place(self):
        """Le carnet est la source de vérité : il doit survivre au diff."""
        from data.orderbook_ws import _apply_depth_update, _book_map
        carnet = _book_map([[100.0, 5.0], [99.0, 3.0]])
        _apply_depth_update(carnet, [[98.0, 2.0]], is_bids=True)
        _apply_depth_update(carnet, [[97.0, 1.0]], is_bids=True)
        assert carnet == {100.0: 5.0, 99.0: 3.0, 98.0: 2.0, 97.0: 1.0}

    def test_vue_bornee_mais_carnet_complet(self):
        """La vue est plafonnée ; le carnet profond reste intact pour les diffs."""
        from data.orderbook_ws import _apply_depth_update, _book_map, _BOOK_VUE
        carnet = _book_map([[1000.0 - i, 1.0] for i in range(_BOOK_VUE + 150)])
        result = _apply_depth_update(carnet, [], is_bids=True)
        assert len(result) == _BOOK_VUE
        assert len(carnet) == _BOOK_VUE + 150
        assert result[0][0] == 1000.0          # la vue part bien du meilleur prix
        # un niveau hors vue reste modifiable et remonte s'il redevient le meilleur
        _apply_depth_update(carnet, [[2000.0, 7.0]], is_bids=True)
        assert _apply_depth_update(carnet, [], is_bids=True)[0] == [2000.0, 7.0]


# ── Test Drawdown Realtime ───────────────────────────────────────────────────

class TestDrawdownRealtime:
    def test_config_params_exist(self):
        from utils.config import DD_REALTIME_ENABLED, DD_CURVE_INTERVAL_SEC
        assert isinstance(DD_REALTIME_ENABLED, bool)
        assert DD_CURVE_INTERVAL_SEC > 0

    def test_paper_engine_has_dd_fields(self):
        """PaperEngine doit avoir les champs drawdown temps réel."""
        from execution.paper_trading import PaperEngine
        engine = PaperEngine()
        assert hasattr(engine, "_current_dd_pct")
        assert hasattr(engine, "_last_curve_ts")
        assert engine._current_dd_pct == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
