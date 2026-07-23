"""tests/test_paper_trading.py — Tests unitaires du PaperEngine.

Lance avec : python -m pytest tests/test_paper_trading.py -v
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Permettre les imports depuis la racine du projet
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_engine():
    """Crée un PaperEngine isolé avec une config de test (sans persistance)."""
    import utils.config as cfg

    # Patch des constantes de config pour les tests
    cfg.PAPER_INITIAL_CAPITAL  = 10_000.0
    cfg.PAPER_RISK_PCT         = 0.01        # 1% par trade
    cfg.PAPER_SLIPPAGE_BPS     = 0.0         # pas de slippage → calculs exacts
    cfg.PAPER_SPREAD_BPS       = 0.0
    cfg.PAPER_FEE_BPS          = 0.0         # pas de frais → isoler la logique PnL
    cfg.PAPER_FUNDING_RATE_8H  = 0.0
    cfg.PAPER_MAX_POSITIONS    = 5
    cfg.PAPER_MAX_EXPOSURE_PCT = 0.80
    cfg.PAPER_TRAILING_STOP    = False
    cfg.PAPER_TRAILING_PCT     = 0.8
    cfg.PAPER_STATE_FILE       = Path("/tmp/test_paper_state.json")
    cfg.PAPER_JOURNAL_FILE     = Path("/tmp/test_paper_journal.json")
    cfg.PAPER_JOURNAL_CSV      = Path("/tmp/test_paper_journal.csv")

    # Supprimer les fichiers de test pour partir propre
    for f in (cfg.PAPER_STATE_FILE, cfg.PAPER_JOURNAL_FILE, cfg.PAPER_JOURNAL_CSV):
        f.unlink(missing_ok=True)

    from execution.paper_trading import PaperEngine
    engine = PaperEngine()
    # Reset complet (au cas où un fichier de state existait)
    engine.cash         = cfg.PAPER_INITIAL_CAPITAL
    engine.realized_pnl = 0.0
    engine.positions    = {}
    engine.trades       = []
    engine._equity_curve = [{"ts": "2026-01-01T00:00:00+00:00", "equity": cfg.PAPER_INITIAL_CAPITAL, "dd_pct": 0.0}]
    engine._peak_equity = cfg.PAPER_INITIAL_CAPITAL
    return engine


def _signal(
    sym="BTC/USDT", side="ACHAT", price=50_000.0,
    sl=49_000.0, tp1=51_500.0, tp2=52_500.0, tp3=53_500.0,
    score=8, source="test",
) -> dict:
    return {
        "symbol": sym, "side": side, "price": price,
        "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "score": score, "source": source,
        "correlation_id": f"test_{sym}_{side}",
        "active": True, "atr": 500.0,
    }


def run(coro):
    return asyncio.run(coro)


# ── Tests ouverture de position ───────────────────────────────────────────────

class TestOpenPosition:

    def test_ouverture_long_basique(self):
        eng = _make_engine()
        sig = _signal()
        pos = run(eng.open_position(sig))
        assert pos is not None
        assert pos.side == "LONG"
        assert pos.symbol == "BTC/USDT"
        assert pos.entry_price == pytest.approx(50_000.0, rel=1e-4)
        assert "BTC/USDT" in eng.positions

    def test_ouverture_short(self):
        eng = _make_engine()
        sig = _signal(side="VENTE", sl=51_000.0, tp1=48_500.0, tp2=47_500.0, tp3=46_500.0)
        pos = run(eng.open_position(sig))
        assert pos is not None
        assert pos.side == "SHORT"

    def test_ouverture_crypto_refusee_par_risque_portefeuille_est_sans_effet(self, monkeypatch):
        """Le garde R3 central doit précéder toute mutation du portefeuille crypto."""
        import core.portfolio_risk as pr
        from core.forex_engine import forex_state
        from core.swing_engine import swing_state

        eng = _make_engine()
        monkeypatch.setitem(swing_state, "positions", {})
        monkeypatch.setitem(swing_state, "equity", 10_000.0)
        monkeypatch.setitem(forex_state, "positions", {})
        monkeypatch.setitem(forex_state, "equity", 10_000.0)
        monkeypatch.setattr(pr, "RISK_MAX_STRATEGY_PCT", 1.0)
        monkeypatch.setattr(pr, "RISK_MAX_CLUSTER_PCT", 5_000.0)
        monkeypatch.setattr(pr, "RISK_MAX_GROSS_PCT", 5_000.0)
        monkeypatch.setattr(pr, "RISK_MAX_NET_PCT", 5_000.0)

        cash_before = eng.cash
        pos = run(eng.open_position(_signal()))

        assert pos is None
        assert eng.cash == cash_before
        assert eng.positions == {}
        assert eng._last_prices == {}

    def test_double_position_meme_symbole_refusee(self):
        eng = _make_engine()
        run(eng.open_position(_signal()))
        pos2 = run(eng.open_position(_signal()))
        assert pos2 is None  # déjà une position sur BTC/USDT

    def test_signal_sans_sl_refuse(self):
        eng = _make_engine()
        sig = _signal(sl=0.0)
        pos = run(eng.open_position(sig))
        assert pos is None

    def test_sl_invalide_long_refuse(self):
        """SL >= prix pour un LONG → doit être refusé."""
        eng = _make_engine()
        sig = _signal(sl=51_000.0)  # SL > prix d'entrée pour un LONG
        pos = run(eng.open_position(sig))
        assert pos is None

    def test_position_sizing_risque(self):
        """La taille de position respecte la règle risk_pct / sl_distance."""
        import utils.config as cfg
        eng = _make_engine()
        # Isoler la formule de sizing : supprimer les plafonds APRÈS _make_engine
        cfg.PAPER_MAX_EXPOSURE_PCT = 1.0      # pas de plafond exposition
        cfg.PAPER_MAX_POSITIONS    = 1         # cap par position = equity * 1.0 / 1 = 10000
        price = 50_000.0
        sl    = 49_000.0          # sl_dist = 1000 = 2%
        sig   = _signal(price=price, sl=sl)
        pos   = run(eng.open_position(sig))
        assert pos is not None
        # risk_usdt = 10000 × 1% = 100
        # size = 100 / 0.02 = 5000 USDT
        assert pos.size_usdt == pytest.approx(5000.0, rel=1e-3)
        # Restaurer
        cfg.PAPER_MAX_EXPOSURE_PCT = 0.80
        cfg.PAPER_MAX_POSITIONS    = 5

    def test_cash_diminue_a_louverture(self):
        eng = _make_engine()
        cash_avant = eng.cash
        run(eng.open_position(_signal()))
        assert eng.cash < cash_avant

    def test_max_positions(self, monkeypatch):
        import execution.paper_trading as paper_trading

        eng = _make_engine()
        monkeypatch.setattr(paper_trading, "PAPER_MAX_POSITIONS", 2)
        run(eng.open_position(_signal(sym="BTC/USDT")))
        run(eng.open_position(_signal(sym="ETH/USDT", sl=3_900.0, price=4_000.0, tp1=4_100.0, tp2=4_200.0, tp3=4_300.0)))
        # 3ème position → refusée
        pos3 = run(eng.open_position(_signal(sym="SOL/USDT", price=100.0, sl=95.0, tp1=105.0, tp2=110.0, tp3=115.0)))
        assert pos3 is None


# ── Tests SL / TP ─────────────────────────────────────────────────────────────

class TestSLTP:

    def test_sl_long_ferme_position(self):
        eng = _make_engine()
        run(eng.open_position(_signal(price=50_000.0, sl=49_000.0)))
        # Simuler un prix sous le SL
        msgs = run(eng.update_price("BTC/USDT", 48_500.0))
        assert len(msgs) > 0
        assert "SL" in msgs[0].upper()
        assert "BTC/USDT" not in eng.positions
        assert len(eng.trades) == 1
        assert eng.trades[0].exit_reason == "sl"
        assert eng.trades[0].pnl_usdt < 0  # trade perdant

    def test_tp1_long_ferme_un_tiers(self):
        eng = _make_engine()
        run(eng.open_position(_signal(price=50_000.0, sl=49_000.0, tp1=51_500.0, tp2=52_500.0, tp3=53_500.0)))
        remaining_before = eng.positions["BTC/USDT"].remaining_pct
        msgs = run(eng.update_price("BTC/USDT", 51_600.0))
        pos = eng.positions.get("BTC/USDT")
        assert pos is not None  # toujours ouverte
        assert pos.tp1_hit
        assert pos.sl_at_be
        assert pos.sl == pytest.approx(50_000.0)  # SL déplacé au BE
        assert pos.remaining_pct == pytest.approx(1 - 1/3, rel=1e-3)
        assert len(eng.trades) == 0  # pas encore fermée complètement

    def test_tp_cascade_ferme_entierement(self):
        eng = _make_engine()
        run(eng.open_position(_signal(price=50_000.0, sl=49_000.0, tp1=51_500.0, tp2=52_500.0, tp3=53_500.0)))
        run(eng.update_price("BTC/USDT", 51_600.0))  # TP1
        run(eng.update_price("BTC/USDT", 52_600.0))  # TP2
        run(eng.update_price("BTC/USDT", 53_600.0))  # TP3
        assert "BTC/USDT" not in eng.positions
        assert len(eng.trades) == 1
        assert eng.trades[0].exit_reason == "tp_cascade"
        assert eng.trades[0].pnl_usdt > 0

    def test_sl_short_ferme_position(self):
        eng = _make_engine()
        sig = _signal(side="VENTE", price=50_000.0, sl=51_000.0,
                      tp1=48_500.0, tp2=47_500.0, tp3=46_500.0)
        run(eng.open_position(sig))
        msgs = run(eng.update_price("BTC/USDT", 51_500.0))
        assert "BTC/USDT" not in eng.positions
        assert eng.trades[0].pnl_usdt < 0

    def test_pnl_positif_tp1_long(self):
        eng = _make_engine()
        run(eng.open_position(_signal(price=50_000.0, sl=49_000.0,
                                      tp1=51_000.0, tp2=52_000.0, tp3=53_000.0)))
        initial_cash = eng.cash
        # Prix passe tp1 et tp2 et tp3
        run(eng.update_price("BTC/USDT", 51_100.0))
        run(eng.update_price("BTC/USDT", 52_100.0))
        run(eng.update_price("BTC/USDT", 53_100.0))
        # PnL réalisé doit être positif
        assert eng.realized_pnl > 0
        assert eng.cash > initial_cash


# ── Tests statistiques ────────────────────────────────────────────────────────

class TestStats:

    def test_stats_sans_trade(self):
        eng = _make_engine()
        stats = eng.get_stats()
        assert stats["total_trades"] == 0
        assert stats["winrate"] == 0.0
        assert stats["equity"] == pytest.approx(10_000.0, rel=1e-3)

    def test_winrate_calcule_correctement(self):
        eng = _make_engine()
        # Trade gagnant : TP3
        run(eng.open_position(_signal(sym="BTC/USDT", price=50_000.0, sl=49_000.0,
                                      tp1=51_500.0, tp2=52_500.0, tp3=53_500.0)))
        run(eng.update_price("BTC/USDT", 53_600.0))

        # Trade perdant : SL
        run(eng.open_position(_signal(sym="ETH/USDT", price=4_000.0, sl=3_900.0,
                                      tp1=4_150.0, tp2=4_300.0, tp3=4_450.0)))
        run(eng.update_price("ETH/USDT", 3_800.0))

        stats = eng.get_stats()
        assert stats["total_trades"] == 2
        assert stats["wins"] == 1
        assert stats["losses"] == 1
        assert stats["winrate"] == pytest.approx(50.0, rel=0.01)

    def test_equity_curve_non_vide(self):
        eng = _make_engine()
        # Ouvrir puis fermer une position
        run(eng.open_position(_signal(price=50_000.0, sl=49_000.0, tp1=51_000.0, tp2=52_000.0, tp3=53_000.0)))
        run(eng.update_price("BTC/USDT", 53_100.0))
        curve = eng.get_equity_curve(200)
        assert len(curve) >= 2
        assert all("equity" in p and "ts" in p and "dd_pct" in p for p in curve)


# ── Tests fermeture manuelle ──────────────────────────────────────────────────

class TestManual:

    def test_fermeture_manuelle(self):
        eng = _make_engine()
        run(eng.open_position(_signal(price=50_000.0, sl=49_000.0)))
        trade = run(eng.close_position_manual("BTC/USDT", 51_000.0))
        assert trade is not None
        assert trade.exit_reason == "manual"
        assert "BTC/USDT" not in eng.positions
        assert len(eng.trades) == 1

    def test_fermeture_manuelle_symbole_inexistant(self):
        eng = _make_engine()
        trade = run(eng.close_position_manual("SOL/USDT", 100.0))
        assert trade is None


# ── Tests reset ───────────────────────────────────────────────────────────────

class TestReset:

    def test_reset_remet_a_zero(self):
        eng = _make_engine()
        run(eng.open_position(_signal()))
        run(eng.reset())
        assert len(eng.positions) == 0
        assert len(eng.trades) == 0
        assert eng.cash == pytest.approx(10_000.0, rel=1e-4)
        assert eng.realized_pnl == pytest.approx(0.0, abs=1e-6)
