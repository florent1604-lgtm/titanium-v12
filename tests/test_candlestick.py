"""Bibliothèque de bougies : patterns clés + biais contextuel (tendance)."""
import pandas as pd

from core import candlestick_engine as ce


def _df(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def test_avalement_haussier():
    # rouge puis grande verte qui l'englobe
    df = _df([[10, 10.2, 9.5, 9.6], [9.5, 11.0, 9.4, 10.9], [9.55, 10.0, 9.4, 9.5]][:2] +
             [[9.5, 11.0, 9.4, 10.9]])
    df = _df([[11, 11, 10, 10.1], [10.2, 10.3, 9.6, 9.7], [9.65, 11.2, 9.6, 11.1]])
    pats = [p.name for p in ce.analyze(df)]
    assert "avalement_haussier" in pats


def test_marteau_candidat_et_contexte():
    df = _df([[11, 11, 10.5, 10.6], [10.6, 10.7, 10.2, 10.3], [10.0, 10.1, 9.0, 9.95]])
    pats = ce.analyze(df)
    assert any(p.name == "marteau" for p in pats)
    # marteau = CANDIDAT (confirm=True) → aucun biais tant que non confirmé (red-team Codex)
    dn = ce.net_bias(pats, uptrend=False)   # downtrend : marteau en attente de confirmation
    assert dn["direction"] == 0 and "marteau" in dn["pending_confirmation"]
    # en uptrend : le marteau est carrément filtré par le contexte
    up = ce.net_bias(pats, uptrend=True)
    assert up["direction"] == 0 and "marteau" not in up["pending_confirmation"]


def test_bougie_plate_nest_pas_un_doji():
    # H=L=O=C : aucune amplitude → aucun pattern (et surtout pas un doji)
    df = _df([[10, 10.5, 9.5, 10.1], [10.1, 10.4, 9.9, 10.2], [10.0, 10.0, 10.0, 10.0]])
    assert ce.analyze(df) == []


def test_doji_non_traite_comme_baissier():
    # bougie 1 = doji (ni bull ni bear) suivie d'une bougie : pas d'avalement/harami baissier
    df = _df([[10, 11, 9, 10.05], [10.05, 10.06, 9.94, 10.0], [10.0, 10.8, 9.9, 10.7]])
    names = [p.name for p in ce.analyze(df)]
    assert "avalement_baissier" not in names and "harami_baissier" not in names


def test_outside_doji_nest_pas_baissier():
    df = _df([[10, 10.5, 9.5, 10.1], [10, 11, 9, 10.2], [10, 12, 8, 10]])
    assert "outside_bar" not in [p.name for p in ce.analyze(df)]


def test_pattern_trois_bougies_refuse_premiere_invalide():
    df = _df([[10, 9, 11, 9.5], [9.5, 10.5, 9.4, 10.4], [10.4, 11.4, 10.3, 11.3]])
    assert ce.analyze(df) == []


def test_trois_soldats_exige_trois_corps_francs():
    df = _df([[10.0, 10.3, 9.9, 10.1],
              [10.1, 11.1, 10.0, 11.0],
              [11.0, 12.0, 10.9, 11.9]])
    assert "trois_soldats" not in [p.name for p in ce.analyze(df)]


def test_net_bias_une_seule_contribution():
    # avalement haussier (confirm=False) domine ; pas de somme de patterns corrélés
    df = _df([[11, 11, 10, 10.1], [10.2, 10.3, 9.6, 9.7], [9.65, 11.2, 9.6, 11.1]])
    nb = ce.net_bias(ce.analyze(df), uptrend=False)
    assert nb["direction"] == 1 and len(nb["patterns"]) == 1


def test_etoile_du_soir():
    # hausse, petite bougie, forte baisse
    df = _df([[10, 11.0, 9.9, 10.95], [11.0, 11.2, 10.9, 11.05], [11.0, 11.1, 9.8, 9.9]])
    assert any(p.name == "etoile_soir" for p in ce.analyze(df))


def test_doji_indecision():
    df = _df([[10, 10.5, 9.5, 10.2], [10.2, 10.4, 10.0, 10.25], [10.2, 10.6, 9.8, 10.21]])
    pats = ce.analyze(df)
    assert any(p.kind == "indecision" for p in pats)


def test_marubozu_continuation():
    df = _df([[10, 10.1, 9.9, 10.0], [10, 10.05, 9.95, 10.0], [10.0, 11.0, 10.0, 10.98]])
    assert any(p.name == "marubozu" and p.direction == 1 for p in ce.analyze(df))


def test_failsafe_short_df():
    assert ce.analyze(_df([[10, 10, 10, 10]])) == []
    assert ce.analyze(None) == []


def test_meaning_present():
    df = _df([[11, 11, 10, 10.1], [10.2, 10.3, 9.6, 9.7], [9.65, 11.2, 9.6, 11.1]])
    for p in ce.analyze(df):
        assert p.meaning and isinstance(p.meaning, str)


# ── Automate de confirmation N+1 (un candidat n'agit qu'une fois validé) ───────

def test_confirmation_n_plus_1():
    # N−1 = marteau (candidat, confirm=True) en downtrend ; N = bougie qui CONFIRME
    df = _df([[11.0, 11.1, 10.4, 10.5],       # contexte baissier
              [10.5, 10.6, 9.8, 9.9],
              [10.0, 10.1, 9.0, 9.95],         # marteau (N−1)
              [10.0, 10.4, 9.96, 10.3]])       # N : clôture 10.3 > 9.95 → confirme
    out = ce.net_bias_on_df(df, uptrend=False)
    assert out["direction"] == 1 and "marteau" in out["confirmed_from_prev"]


def test_candidat_non_confirme_reste_neutre():
    # même marteau, mais N est baissière → PAS de confirmation → aucun biais actionnable
    df = _df([[11.0, 11.1, 10.4, 10.5],
              [10.5, 10.6, 9.8, 9.9],
              [10.0, 10.1, 9.0, 9.95],         # marteau (N−1)
              [9.95, 10.0, 9.5, 9.6]])         # N : baissière → n'invalide pas mais ne confirme pas
    out = ce.net_bias_on_df(df, uptrend=False)
    assert out["direction"] == 0 and "marteau" not in out["confirmed_from_prev"]
