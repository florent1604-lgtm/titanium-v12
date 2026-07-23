"""tools/intraday_oos.py — Les 3 rescapes intraday tiennent-ils HORS ECHANTILLON ?

Le panier intraday (config fixe) est negatif ; seuls XRP/AVAX/LINK restaient
positifs sur l'historique COMPLET. Mais 3/10 peut etre de la chance. Test decisif :
on coupe le temps en IS (70% ancien) / OOS (30% recent inedit), on applique la
MEME config fixe, et on regarde si l'avantage SURVIT sur la periode jamais vue.

  IS + et OOS +  -> edge robuste (candidat serieux)
  IS + et OOS -  -> sur-apprentissage / chance (a jeter)

Reutilise daily_returns() (config fixe, cout maker) de tools.intraday_basket.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from tools.intraday_basket import daily_returns, sharpe, SYMBOLS

WATCH = {"XRPUSDT", "AVAXUSDT", "LINKUSDT"}   # les 3 rescapes a valider


def split_oos(ds: pd.Series, frac_is: float = 0.70):
    """Coupe la serie de rendements au point temporel `frac_is`."""
    if ds is None or len(ds) < 20:
        return None, None
    cut = ds.index[int(len(ds) * frac_is)]
    return ds[ds.index < cut], ds[ds.index >= cut]


def main() -> None:
    print("=== TEST OUT-OF-SAMPLE INTRADAY (config fixe, coupe temporelle 70/30) ===")
    print("    verdict : IS+ ET OOS+ = robuste ; IS+ / OOS- = chance/sur-apprentissage\n")
    print("%-9s %8s %8s %8s %8s   %s" % ("crypto", "Sh_IS", "Sh_OOS", "R_IS", "R_OOS", "verdict"))
    for s in SYMBOLS:
        ds = daily_returns(s)
        is_, oos = split_oos(ds)
        if is_ is None or oos is None or len(oos) < 10:
            print("%-9s   donnees insuffisantes" % s); continue
        shi, sho = sharpe(is_), sharpe(oos)
        ri, ro = is_.sum(), oos.sum()
        if shi > 0 and sho > 0:
            v = "ROBUSTE ***" if s in WATCH else "robuste"
        elif shi > 0 and sho <= 0:
            v = "chance (OOS s'effondre)"
        elif shi <= 0 and sho > 0:
            v = "IS negatif (bruit)"
        else:
            v = "negatif partout"
        star = " <-- rescape" if s in WATCH else ""
        print("%-9s %8.2f %8.2f %8.2f %8.2f   %s%s" % (s, shi, sho, ri, ro, v, star))
    print("\n  IS = periode d'apprentissage ; OOS = 30% recent JAMAIS vu par la config.")


if __name__ == "__main__":
    main()
