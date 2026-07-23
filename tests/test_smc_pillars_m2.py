"""tests/test_smc_pillars_m2.py — contrat des piliers SMC corrigés (lot M2).

Diagnostic Codex (22/07/2026), vérifié dans le code puis corrigé :
  · _liquidity : `sweep OR bool(detect_fvg)` sur TOUT l'historique rendait bull ET
    bear vrais en permanence → pilier 0/20. Corrigé : FVG ACTIVE au contact du prix.
  · detect_liquidity_sweep : tampon fixe 0,3 % non normalisé, aberrant entre classes
    d'actifs. Corrigé : tampon en fraction d'ATR quand l'ATR est fourni.
  · ote_ob : ne testait que `in_ote`, aucun OB malgré le nom. Corrigé : OTE ET OB actif.

Ces tests encodent le CONTRAT, pas l'implémentation, et prouvent que l'ancien
comportement cassé ne peut pas revenir.
"""
import numpy as np
import pandas as pd

from core import confluence_adapter as ca
from core import smc_engine as smc


def _rows(rows):
    """DataFrame OHLC à partir de tuples (open, high, low, close)."""
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="h", tz="UTC")
    o, h, l, c = zip(*rows)
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c,
                         "v": [100.0] * len(rows)}, index=idx)


# ── Fix B : _liquidity directionnel, FVG au contact du prix ───────────────────

def _liquidity_ancienne(df):
    """Oracle : formule EXACTE d'avant le correctif, gardée pour documenter le bug."""
    bull = smc.detect_liquidity_sweep(df, "ACHAT") or bool(smc.detect_fvg(df, "ACHAT"))
    bear = smc.detect_liquidity_sweep(df, "VENTE") or bool(smc.detect_fvg(df, "VENTE"))
    if bull and not bear:
        return 1
    if bear and not bull:
        return -1
    return 0


def _ramp(a, b):
    """Rampe graduelle SANS gap (pas 1, demi-amplitude 2) entre deux niveaux."""
    n = max(2, int(abs(b - a)) + 1)
    return [(p, p + 2, p - 2, p) for p in np.linspace(a, b, n)]


def test_or_bug_documente_puis_corrige():
    """LE 0/20, reproduit puis corrigé. Cadre : une FVG haussière lointaine EN BAS,
    une FVG baissière lointaine EN HAUT, un plateau au milieu, un sweep baissier net
    à la fin. L'ancienne formule voit une FVG de CHAQUE côté (n'importe où) →
    bull=bear=True → 0 : elle MASQUE le sweep. Le correctif ignore les FVG hors
    d'atteinte et laisse le sweep parler → −1."""
    rows = [(80, 81, 79, 80), (84, 85, 83, 84), (88, 89, 87, 88)]            # bull FVG lointaine [81,87]
    rows += _ramp(90, 118)
    rows += [(118, 119, 117, 118), (114, 115, 113, 114), (110, 111, 109, 110)]  # bear FVG lointaine [111,117]
    rows += _ramp(108, 100)
    rows += [(100.0, 100.2, 99.8, 100.0) for _ in range(56)]                 # plateau plat
    rows.append((100.0, 101.0, 99.9, 99.85))                                 # sweep baissier net
    df = _rows(rows)
    price = float(df["close"].iloc[-1])
    atr = smc.compute_atr(df)
    tol = smc.compute_fib_tolerance(df.tail(50), price, atr)

    # des FVG des DEUX côtés existent (condition du bug), mais toutes LOIN du prix
    assert smc.detect_fvg(df, "ACHAT") and smc.detect_fvg(df, "VENTE")
    for zones in (smc.detect_fvg(df, "ACHAT"), smc.detect_fvg(df, "VENTE")):
        for bot, top in zones:
            assert not ((bot - tol) <= price <= (top + tol)), "une FVG lointaine reste comptée"

    assert _liquidity_ancienne(df) == 0            # l'ancienne formule masque le sweep
    assert ca._liquidity(df, price, atr) == -1     # le correctif le révèle


def test_liquidity_directionnelle_sur_sweep_propre():
    """Marché plat (aucune FVG) + sweep baissier net → −1 sans ambiguïté ;
    l'ancienne formule y arrivait aussi, mais ici on VERROUILLE la directionnalité."""
    base = [(100.0, 100.2, 99.8, 100.0) for _ in range(56)]
    base.append((100.0, 101.0, 99.9, 99.85))          # mèche 101 > plus-haut 100.2, clôture sous
    df = _rows(base)
    price = float(df["close"].iloc[-1])
    assert smc.detect_fvg(df, "ACHAT") == [] and smc.detect_fvg(df, "VENTE") == []
    assert ca._liquidity(df, price, smc.compute_atr(df)) == -1


def test_liquidity_neutre_si_aucune_fvg_au_contact():
    """Sans sweep ni FVG proche, la liquidité est muette (0), pas inventée."""
    rows = [(p, p + 0.3, p - 0.3, p) for p in np.linspace(100, 110, 70)]  # tendance lisse, sans gap
    df = _rows(rows)
    price = float(df["close"].iloc[-1])
    assert ca._liquidity(df, price, smc.compute_atr(df)) == 0


def test_fvg_actionnable_exige_la_proximite():
    """La même FVG compte au contact du prix et ne compte plus loin d'elle."""
    rows = [(90, 91, 89, 90), (95, 96, 94, 95), (99, 100, 98, 99)]        # bull FVG ~[91,98]
    rows += [(p, p + 0.3, p - 0.3, p) for p in np.linspace(99, 99, 60)]
    df = _rows(rows)
    assert ca._fvg_actionnable(df, "ACHAT", price=95.0, tol=1.0) is True   # dans la zone
    assert ca._fvg_actionnable(df, "ACHAT", price=130.0, tol=1.0) is False  # loin au-dessus


# ── Fix A : sweep normalisé ATR, rétrocompatibilité stricte ───────────────────

def _frame_sweep_achat(reclaim_close):
    """50+ barres plates à 100, puis mèche qui perce sous 100 et clôture = reclaim."""
    base = [(100.0, 100.2, 99.8, 100.0) for _ in range(55)]
    base.append((100.0, 100.1, 98.0, reclaim_close))   # mèche à 98, clôture paramétrable
    return _rows(base)


def test_sweep_defaut_inchange_sans_atr():
    """Sans ATR fourni, le comportement historique (tampon 0,3 %) est STRICTEMENT
    conservé — c'est ce qui protège le scorer /16 live d'un effet de bord."""
    # low historique = 99.8 ; confirm = 99.8*1.003 = 100.099. Clôture 100.2 > seuil → sweep.
    assert smc.detect_liquidity_sweep(_frame_sweep_achat(100.2), "ACHAT") is True
    # Clôture 100.05 < 100.099 → pas de reconquête → pas de sweep.
    assert smc.detect_liquidity_sweep(_frame_sweep_achat(100.05), "ACHAT") is False


def test_sweep_atr_remplace_le_tampon_fixe():
    """Avec ATR, le seuil de reconquête suit la volatilité, pas un pourcentage fixe."""
    df = _frame_sweep_achat(100.2)
    atr = smc.compute_atr(df)
    # tampon serré (ATR petit) → reconquête franchie
    assert smc.detect_liquidity_sweep(df, "ACHAT", atr=atr, atr_mult=0.1) is True
    # tampon énorme → le seuil monte au-dessus de la clôture → refusé
    assert smc.detect_liquidity_sweep(df, "ACHAT", atr=atr, atr_mult=50.0) is False


# ── Fix C : ote_ob exige un OB, pas seulement in_ote ──────────────────────────

def test_ote_ob_refuse_sans_ob():
    """Dans la golden zone mais sans OB actif au contact → pilier muet (0).
    L'ancien code renvoyait la direction sur le seul `in_ote`."""
    df = _rows([(p, p + 0.3, p - 0.3, p) for p in np.linspace(100, 110, 60)])
    fib_ctx = {"available": True, "in_ote": True, "invalidated": False, "direction": 1}
    assert ca._ote_ob(df, price=105.0, fib_ctx=fib_ctx) == 0


def test_ote_ob_muet_hors_zone_ou_invalide():
    df = _rows([(p, p + 0.3, p - 0.3, p) for p in np.linspace(100, 110, 60)])
    price = 105.0
    assert ca._ote_ob(df, price, {"available": True, "in_ote": False,
                                  "invalidated": False, "direction": 1}) == 0
    assert ca._ote_ob(df, price, {"available": True, "in_ote": True,
                                  "invalidated": True, "direction": 1}) == 0
    assert ca._ote_ob(df, price, {"available": False}) == 0
