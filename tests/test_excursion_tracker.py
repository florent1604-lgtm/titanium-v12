"""Yeux de Cloe — l'enregistreur d'excursions mesure-t-il juste, et ne casse-t-il jamais ?

Prouve : MAE/MFE/giveback corrects en long ET en short, le drapeau `censored` (sans lequel
toute estimation future du MFE serait biaisée à la baisse), et surtout la RÉSILIENCE :
un enregistreur qui plante ne doit JAMAIS perturber la gestion d'une position.
"""
import json

from feedback import excursion_tracker as ex


def _run(side, entry, r, prices):
    """Rejoue une suite de prix dans l'observateur et rend l'état final."""
    st = {"entry": entry, "r": r, "side": side}
    for i, p in enumerate(prices):
        ex.observe(st, side=side, entry=entry, cur=p, r=r, ts=1000.0 + i * 15)
    return st


# ── MAE / MFE ───────────────────────────────────────────────────────────────

def test_long_gagnant_mfe_et_mae():
    # long à 100, R=10. Descend à 95 (−0.5R) puis monte à 130 (+3R).
    st = _run(1, 100.0, 10.0, [100.0, 95.0, 110.0, 130.0])
    assert round(st["mfe_R"], 2) == 3.0        # sommet favorable
    assert round(st["mae_R"], 2) == -0.5       # pire moment adverse
    assert st["ts_mfe"] is not None


def test_short_symetrique():
    # short à 100, R=10 : le prix qui BAISSE est favorable.
    st = _run(-1, 100.0, 10.0, [100.0, 105.0, 90.0, 80.0])
    assert round(st["mfe_R"], 2) == 2.0        # 100→80 = +2R pour un short
    assert round(st["mae_R"], 2) == -0.5       # 100→105 = −0.5R


def test_giveback_mesure_la_restitution():
    # monte à +3R puis retombe à +0.5R → on a restitué 2.5R (le regret).
    st = _run(1, 100.0, 10.0, [100.0, 130.0, 105.0])
    assert round(st["mfe_R"], 2) == 3.0
    assert round(st["giveback_R"], 2) == 2.5


def test_giveback_ignore_ce_qui_precede_le_sommet():
    # le creux SURVIENT AVANT le sommet → ce n'est pas une restitution.
    st = _run(1, 100.0, 10.0, [100.0, 90.0, 130.0])
    assert round(st["mae_R"], 2) == -1.0
    assert st.get("giveback_R", 0.0) == 0.0


def test_extrema_monotones_jamais_de_recul():
    st = _run(1, 100.0, 10.0, [100.0, 130.0, 100.0, 120.0])
    assert round(st["mfe_R"], 2) == 3.0        # le sommet ne redescend pas
    st2 = _run(1, 100.0, 10.0, [100.0, 80.0, 100.0])
    assert round(st2["mae_R"], 2) == -2.0      # le creux ne remonte pas


def test_r_invalide_ne_leve_pas():
    st = {"entry": 100.0, "r": 0.0, "side": 1}
    ex.observe(st, side=1, entry=100.0, cur=110.0, r=0.0)   # R nul → ignoré, pas d'exception
    assert "mfe_R" not in st


# ── Censure (le champ critique) ─────────────────────────────────────────────

class _Deal:
    def __init__(self, comment, profit=-5.0, price=95.0, t=2000.0):
        self.comment, self.profit, self.price, self.time = comment, profit, price, t
        self.swap = 0.0
        self.commission = 0.0
        self.entry = 1


class _MT5:
    DEAL_ENTRY_OUT = 1
    TIMEFRAME_M1 = 1

    def __init__(self, comment="[sl 95.0]"):
        self._c = comment

    def history_deals_get(self, position=None):
        return [_Deal(self._c)]

    def copy_rates_range(self, *a, **k):
        return None                     # force le repli sur le suivi 15 s


def test_sortie_au_sl_est_marquee_censuree(tmp_path, monkeypatch):
    """Un trade coupé au SL a un MFE TRONQUÉ : sans ce drapeau, toute estimation
    future du MFE serait biaisée à la baisse — et rien ne pourrait le rattraper."""
    monkeypatch.setattr(ex, "OUT_DIR", tmp_path)
    monkeypatch.setattr(ex, "_entry_context", lambda t: {})
    st = _run(1, 100.0, 10.0, [100.0, 120.0, 95.0])
    st["ts_entry_obs"] = 1000.0
    rec = ex.record_closed(_MT5("[sl 95.0]"), "777", st, symbol="EURUSD")
    assert rec["censored"] is True and rec["exit_reason"] == "sl"


def test_sortie_au_tp_non_censuree(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "OUT_DIR", tmp_path)
    monkeypatch.setattr(ex, "_entry_context", lambda t: {})
    st = _run(1, 100.0, 10.0, [100.0, 130.0])
    st["ts_entry_obs"] = 1000.0
    rec = ex.record_closed(_MT5("[tp 130.0]"), "778", st, symbol="EURUSD")
    assert rec["censored"] is False and rec["exit_reason"] == "tp"


def test_ligne_ecrite_et_schema_complet(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "OUT_DIR", tmp_path)
    monkeypatch.setattr(ex, "_entry_context", lambda t: {"n_pillars": 2})
    st = _run(1, 100.0, 10.0, [100.0, 120.0, 95.0])
    st["ts_entry_obs"] = 1000.0
    ex.record_closed(_MT5(), "779", st, symbol="XAUUSD")
    files = list(tmp_path.glob("excursions-*.ndjson"))
    assert len(files) == 1
    rec = json.loads(files[0].read_text(encoding="utf-8").strip())
    for champ in ("schema_version", "trade_id", "symbol", "direction", "mae_R", "mfe_R",
                  "giveback_R", "censored", "exit_reason", "pnl_R", "context",
                  "excursion_source", "r_unit_price"):
        assert champ in rec, f"champ manquant: {champ}"
    assert rec["context"]["n_pillars"] == 2      # la perception d'entrée est jointe


# ── Résilience : ne JAMAIS perturber le trading ─────────────────────────────

def test_enregistreur_casse_ne_remonte_jamais(tmp_path, monkeypatch):
    """Contrainte non négociable : un logger cassé ne doit pas empêcher un trade.
    MT5 en panne → on n'explose PAS, et on enregistre quand même la ligne en mode
    dégradé (sortie `unknown`) plutôt que de perdre l'observation."""
    monkeypatch.setattr(ex, "OUT_DIR", tmp_path)
    monkeypatch.setattr(ex, "_entry_context", lambda t: {})

    class _Explose:
        def history_deals_get(self, position=None):
            raise RuntimeError("MT5 explosé")
        def copy_rates_range(self, *a, **k):
            raise RuntimeError("MT5 explosé")

    st = {"entry": 100.0, "r": 10.0, "side": 1, "ts_entry_obs": 1000.0}
    rec = ex.record_closed(_Explose(), "780", st, symbol="X")   # ne lève pas
    assert rec is not None and rec["exit_reason"] == "unknown"   # dégradé, pas perdu


def test_etat_incomplet_ignore_sans_lever():
    assert ex.record_closed(_MT5(), "781", {}, symbol="X") is None
