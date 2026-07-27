"""Analytique trades démo : catégorisation + agrégation par contexte (pur/testable)."""
from tools import trade_analytics as ta


def test_category():
    assert ta._category("BTCUSD") == "crypto"
    assert ta._category("XAUUSD") == "metals"
    assert ta._category("EURUSD") == "fx"
    assert ta._category("NAS100.fs") == "futures"
    assert ta._category("US500") == "index/cash"


def test_structure_bucket():
    assert ta._structure(3) == "S(~2p)"
    assert ta._structure(15) == "M(~3p)"
    assert ta._structure(30) == "L(~4p)"
    assert ta._structure(60) == "XL(~5p)"


def test_pillars_parse():
    assert ta._pillars("titanium-conf|p4") == 4
    assert ta._pillars("titanium-aggr|p2") == 2
    assert ta._pillars("sans-piliers") is None


def test_stats_winrate_expectancy_pf():
    trades = [
        {"closed": True, "pnl": 2.0, "R": 2.0},
        {"closed": True, "pnl": -1.0, "R": -1.0},
        {"closed": True, "pnl": -1.0, "R": -1.0},
        {"closed": True, "pnl": 3.0, "R": 1.5},
        {"closed": False, "pnl": 0.5, "R": 0.5},   # ouvert → ignoré
    ]
    s = ta._stats(trades)
    assert s["n"] == 4
    assert s["winrate"] == 50.0
    # espérance = (2 -1 -1 +1.5)/4 = 0.375
    assert s["expectancy_R"] == 0.375
    # PF = (2+3) / (1+1) = 2.5
    assert s["profit_factor"] == 2.5
    assert s["sum_pnl"] == 3.0


def test_aggregate_par_dimension():
    trades = [
        {"category": "crypto", "engine": "confluence", "side": "short", "structure": "S(~2p)",
         "hour": "NY(12-17)", "symbol": "BTCUSD", "closed": True, "pnl": -1.0, "R": -1.0},
        {"category": "crypto", "engine": "confluence", "side": "long", "structure": "M(~3p)",
         "hour": "NY(12-17)", "symbol": "ETHUSD", "closed": True, "pnl": 2.0, "R": 2.0},
        {"category": "fx", "engine": "confluence-aggr", "side": "short", "structure": "S(~2p)",
         "hour": "Asie(00-07)", "symbol": "EURUSD", "closed": True, "pnl": -1.0, "R": -1.0},
    ]
    agg = ta.aggregate(trades)
    assert agg["overall"]["n"] == 3
    # dimension side : le short doit ressortir perdant, le long gagnant
    by_side = {r["side"]: r for r in agg["side"]}
    assert by_side["short"]["n"] == 2 and by_side["short"]["expectancy_R"] == -1.0
    assert by_side["long"]["n"] == 1 and by_side["long"]["expectancy_R"] == 2.0


def test_stats_vide():
    assert ta._stats([{"closed": False, "pnl": 1, "R": 1}]) == {"n": 0}
