"""core/candlestick_engine.py — Bibliothèque de bougies japonaises + leur SIGNIFICATION.

Renforce le module d'entrée (audit 17/07/2026 : le bot n'avait qu'UN pattern,
`detect_rejection_candle`). C'est l'outil de CONFIRMATION de la méthode de Florent
(« la confirmation peut venir d'une simple bougie »).

API pure (pandas/numpy), SANS look-ahead : n'analyse que des bougies CLÔTURÉES.
`analyze(df)` → patterns présents sur la dernière bougie close, chacun avec :
  name, direction (+1 haussier / −1 baissier / 0 indécision), kind
  (reversal/continuation/indecision), strength 0..1, confirm (bougie de confirm.
  requise ?), meaning (signification FR).

Chaque détecteur reçoit les 3 dernières bougies (assez pour les patterns 3-bougies).
Le CONTEXTE (tendance amont) affine le sens : un marteau n'est un signal d'achat
qu'APRÈS une baisse ; ici on renvoie le pattern brut + un drapeau `needs_downtrend`
/`needs_uptrend` que le moteur de confluence croisera avec la tendance (EMA200).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd


import math


@dataclass(frozen=True)
class Candle:
    o: float
    h: float
    l: float
    c: float

    @property
    def valid(self) -> bool:
        vals = (self.o, self.h, self.l, self.c)
        return (all(math.isfinite(x) for x in vals)
                and self.h >= self.l and self.h >= max(self.o, self.c)
                and self.l <= min(self.o, self.c))
    @property
    def flat(self) -> bool: return self.h - self.l <= 1e-12   # aucune amplitude réelle
    @property
    def body(self) -> float: return abs(self.c - self.o)
    @property
    def rng(self) -> float: return self.h - self.l            # PAS de plancher : bougie plate → range nul
    @property
    def upper(self) -> float: return self.h - max(self.o, self.c)
    @property
    def lower(self) -> float: return min(self.o, self.c) - self.l
    @property
    def bull(self) -> bool: return self.c > self.o            # strict
    @property
    def bear(self) -> bool: return self.c < self.o            # strict (un doji n'est ni l'un ni l'autre)
    @property
    def mid(self) -> float: return (self.o + self.c) / 2.0


@dataclass(frozen=True)
class Pattern:
    name: str
    direction: int          # +1 haussier, −1 baissier, 0 indécision
    kind: str               # 'reversal' | 'continuation' | 'indecision'
    strength: float         # 0..1 (qualité du pattern)
    confirm: bool           # une bougie de confirmation est-elle requise ?
    meaning: str            # signification en clair
    context: str = ""       # 'needs_downtrend' | 'needs_uptrend' | ''


def _c(row) -> Candle:
    return Candle(float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]))


# ── Patterns 1 bougie ────────────────────────────────────────────────────────

def _doji(a: Candle, prev=None, p2=None) -> Optional[Pattern]:
    if a.body > a.rng * 0.08:
        return None
    if a.upper > a.rng * 0.66 and a.lower < a.rng * 0.10:
        return Pattern("doji_pierre_tombale", -1, "reversal", 0.6, True,
                       "Doji pierre tombale : rejet violent des hauts → épuisement acheteur.", "needs_uptrend")
    if a.lower > a.rng * 0.66 and a.upper < a.rng * 0.10:
        return Pattern("doji_libellule", +1, "reversal", 0.6, True,
                       "Doji libellule : rejet des bas → épuisement vendeur.", "needs_downtrend")
    return Pattern("doji", 0, "indecision", 0.3, True,
                   "Doji : équilibre acheteurs/vendeurs, indécision — attendre confirmation.")


def _marteau(a: Candle, prev=None, p2=None) -> Optional[Pattern]:
    if a.body < a.rng * 0.35 and a.lower > a.rng * 0.55 and a.upper < a.rng * 0.15:
        # marteau (bas de tendance) vs pendu (haut de tendance) → le contexte tranche
        return Pattern("marteau", +1, "reversal", 0.65, True,
                       "Marteau : longue mèche basse, rejet des vendeurs → retournement haussier probable.",
                       "needs_downtrend")
    return None


def _etoile_filante(a: Candle, prev=None, p2=None) -> Optional[Pattern]:
    if a.body < a.rng * 0.35 and a.upper > a.rng * 0.55 and a.lower < a.rng * 0.15:
        return Pattern("etoile_filante", -1, "reversal", 0.65, True,
                       "Étoile filante : longue mèche haute, rejet des acheteurs → retournement baissier probable.",
                       "needs_uptrend")
    return None


def _marubozu(a: Candle, prev=None, p2=None) -> Optional[Pattern]:
    if a.body > a.rng * 0.90:
        d = +1 if a.bull else -1
        return Pattern("marubozu", d, "continuation", 0.6, False,
                       ("Marubozu haussier : pression acheteuse totale, corps plein sans mèche."
                        if a.bull else
                        "Marubozu baissier : pression vendeuse totale, corps plein sans mèche."))
    return None


def _toupie(a: Candle, prev=None, p2=None) -> Optional[Pattern]:
    if a.body < a.rng * 0.30 and a.upper > a.rng * 0.25 and a.lower > a.rng * 0.25:
        return Pattern("toupie", 0, "indecision", 0.3, True,
                       "Toupie : petit corps, mèches des deux côtés → indécision, perte de momentum.")
    return None


# ── Patterns 2 bougies ───────────────────────────────────────────────────────

def _englobante(a: Candle, prev: Candle, p2=None) -> Optional[Pattern]:
    if prev is None:
        return None
    if a.bull and prev.bear and a.c >= prev.o and a.o <= prev.c and a.body > prev.body:
        return Pattern("avalement_haussier", +1, "reversal", 0.75, False,
                       "Avalement haussier : la bougie verte engloutit la rouge → renversement de force acheteur.",
                       "needs_downtrend")
    if a.bear and prev.bull and a.c <= prev.o and a.o >= prev.c and a.body > prev.body:
        return Pattern("avalement_baissier", -1, "reversal", 0.75, False,
                       "Avalement baissier : la bougie rouge engloutit la verte → renversement de force vendeur.",
                       "needs_uptrend")
    return None


def _harami(a: Candle, prev: Candle, p2=None) -> Optional[Pattern]:
    if prev is None or prev.body < prev.rng * 0.5:
        return None
    inside = max(a.o, a.c) <= max(prev.o, prev.c) and min(a.o, a.c) >= min(prev.o, prev.c)
    if inside and a.body < prev.body * 0.6:
        if prev.bear:
            return Pattern("harami_haussier", +1, "reversal", 0.55, True,
                           "Harami haussier : petite bougie dans une grande rouge → ralentissement de la baisse.",
                           "needs_downtrend")
        if prev.bull:
            return Pattern("harami_baissier", -1, "reversal", 0.55, True,
                           "Harami baissier : petite bougie dans une grande verte → ralentissement de la hausse.",
                           "needs_uptrend")
    return None


def _pince(a: Candle, prev: Candle, p2=None) -> Optional[Pattern]:
    if prev is None:
        return None
    tol = (a.rng + prev.rng) * 0.06
    if abs(a.l - prev.l) <= tol and prev.bear and a.bull:
        return Pattern("pince_basse", +1, "reversal", 0.5, True,
                       "Pince basse : deux plus-bas identiques → support défendu, rebond probable.",
                       "needs_downtrend")
    if abs(a.h - prev.h) <= tol and prev.bull and a.bear:
        return Pattern("pince_haute", -1, "reversal", 0.5, True,
                       "Pince haute : deux plus-hauts identiques → résistance défendue, repli probable.",
                       "needs_uptrend")
    return None


def _penetrante(a: Candle, prev: Candle, p2=None) -> Optional[Pattern]:
    if prev is None:
        return None
    if prev.bear and a.bull and a.o < prev.l and a.c > prev.mid and a.c < prev.o:
        return Pattern("penetrante", +1, "reversal", 0.6, True,
                       "Ligne pénétrante : ouverture sous le bas, clôture au-dessus de la mi-bougie rouge → achat.",
                       "needs_downtrend")
    if prev.bull and a.bear and a.o > prev.h and a.c < prev.mid and a.c > prev.o:
        return Pattern("couvert_nuages", -1, "reversal", 0.6, True,
                       "Couverture en nuage noir : ouverture au-dessus du haut, clôture sous la mi-bougie verte → vente.",
                       "needs_uptrend")
    return None


# ── Patterns 3 bougies ───────────────────────────────────────────────────────

def _etoile(a: Candle, prev: Candle, p2: Candle) -> Optional[Pattern]:
    if prev is None or p2 is None:
        return None
    star = prev.body < prev.rng * 0.35
    # 1re bougie = corps FRANC (pas un doji) ; 3e bougie confirme dans le sens (couleur stricte).
    big1 = p2.body > p2.rng * 0.5
    if p2.bear and big1 and star and a.bull and a.c > p2.mid:
        return Pattern("etoile_matin", +1, "reversal", 0.8, False,
                       "Étoile du matin : baisse → indécision → forte hausse. Retournement haussier fiable.",
                       "needs_downtrend")
    if p2.bull and big1 and star and a.bear and a.c < p2.mid:
        return Pattern("etoile_soir", -1, "reversal", 0.8, False,
                       "Étoile du soir : hausse → indécision → forte baisse. Retournement baissier fiable.",
                       "needs_uptrend")
    return None


def _soldats(a: Candle, prev: Candle, p2: Candle) -> Optional[Pattern]:
    if prev is None or p2 is None:
        return None
    big = lambda x: x.body > x.rng * 0.6
    if a.bull and prev.bull and p2.bull and big(a) and big(prev) and big(p2) and a.c > prev.c > p2.c:
        return Pattern("trois_soldats", +1, "continuation", 0.7, False,
                       "Trois soldats blancs : trois hausses franches consécutives → tendance haussière forte.")
    if a.bear and prev.bear and p2.bear and big(a) and big(prev) and big(p2) and a.c < prev.c < p2.c:
        return Pattern("trois_corbeaux", -1, "continuation", 0.7, False,
                       "Trois corbeaux noirs : trois baisses franches consécutives → tendance baissière forte.")
    return None


def _inside_outside(a: Candle, prev: Candle, p2=None) -> Optional[Pattern]:
    if prev is None:
        return None
    if a.h <= prev.h and a.l >= prev.l:
        return Pattern("inside_bar", 0, "indecision", 0.35, True,
                       "Inside bar : compression dans la bougie précédente → cassure imminente, jouer la sortie.")
    if a.h > prev.h and a.l < prev.l:
        if not (a.bull or a.bear):
            return None
        d = +1 if a.bull else -1
        return Pattern("outside_bar", d, "reversal", 0.5, True,
                       "Outside bar : englobe la précédente des deux côtés → prise de contrôle "
                       + ("acheteuse." if a.bull else "vendeuse."))
    return None


_DETECTORS = [_doji, _marteau, _etoile_filante, _marubozu, _toupie,
              _englobante, _harami, _pince, _penetrante,
              _etoile, _soldats, _inside_outside]


def analyze(df: pd.DataFrame) -> List[Pattern]:
    """Patterns présents sur la DERNIÈRE bougie clôturée de df. Fail-safe."""
    if df is None or len(df) < 3:
        return []
    try:
        a = _c(df.iloc[-1]); prev = _c(df.iloc[-2]); p2 = _c(df.iloc[-3])
    except Exception:
        return []
    # Garde validité (red-team Codex) : OHLC finis/cohérents ; bougie plate H=L ≠ doji.
    if not a.valid or not prev.valid or not p2.valid or a.flat:
        return []
    out: List[Pattern] = []
    for det in _DETECTORS:
        try:
            p = det(a, prev, p2)
        except Exception:
            p = None
        if p:
            out.append(p)
    return sorted(out, key=lambda p: -p.strength)


def net_bias(patterns: List[Pattern], *, uptrend: Optional[bool] = None) -> dict:
    """Biais net respectant le CONTEXTE de tendance et la CONFIRMATION (red-team Codex).
    · Un retournement ne compte que CONTRE la tendance (marteau en downtrend, etc.).
    · Un pattern `confirm=True` est un CANDIDAT : il ne donne AUCUN biais tant qu'il
      n'est pas validé par la bougie close suivante (aucune lecture anticipée).
    · Pas de SOMME de patterns corrélés (même bougie) : une seule contribution — le
      pattern confirmé le plus fort. uptrend=None → contexte ignoré."""
    actionable: List[Pattern] = []
    for p in patterns:
        if uptrend is not None:
            if p.context == "needs_downtrend" and uptrend:
                continue
            if p.context == "needs_uptrend" and not uptrend:
                continue
        actionable.append(p)
    confirmed = [p for p in actionable if not p.confirm]
    pending = [p.name for p in actionable if p.confirm]
    if not confirmed:
        return {"direction": 0, "score": 0.0, "patterns": [],
                "pending_confirmation": pending}
    best = max(confirmed, key=lambda p: p.strength)      # une seule contribution
    return {"direction": best.direction, "score": round(best.direction * best.strength, 3),
            "patterns": [best.name], "pending_confirmation": pending}


def _confirms(cand: Pattern, conf: Candle, patt_bar: Candle) -> bool:
    """La bougie de confirmation `conf` (N) valide-t-elle le candidat formé en N−1 ?
    Règle causale : clôture DANS le sens du candidat, au-delà de la clôture du pattern."""
    if cand.direction > 0:
        return conf.bull and conf.c > patt_bar.c
    if cand.direction < 0:
        return conf.bear and conf.c < patt_bar.c
    return False


def net_bias_on_df(df: pd.DataFrame, *, uptrend: Optional[bool] = None) -> dict:
    """Biais ACTIONNABLE sur la dernière bougie clôturée, AVEC automate de confirmation.
    · patterns `confirm=False` sur N : actionnables immédiatement (avalement, marubozu…).
    · patterns `confirm=True` formés en N−1 : actionnables SEULEMENT si la bougie N (déjà
      clôturée) les confirme (`_confirms`). Aucune bougie en formation n'est jamais lue.
    Une seule contribution retenue (la plus forte). Le champ `confirmed_from_prev` liste
    les candidats validés par N+1, `pending_confirmation` ceux qui attendent encore."""
    empty = {"direction": 0, "score": 0.0, "patterns": [],
             "pending_confirmation": [], "confirmed_from_prev": []}
    if df is None or len(df) < 3:
        return empty
    immediate = net_bias(analyze(df), uptrend=uptrend)      # confirm=False sur N
    candidates = []
    if immediate["direction"] != 0 and immediate["patterns"]:
        candidates.append((immediate["direction"], abs(immediate["score"]), immediate["patterns"][0]))

    confirmed_prev: List[str] = []
    if len(df) >= 4:
        try:
            conf = _c(df.iloc[-1]); patt_bar = _c(df.iloc[-2])
            valid_bars = conf.valid and patt_bar.valid and not conf.flat
        except Exception:
            valid_bars = False
        if valid_bars:
            for p in analyze(df.iloc[:-1]):                 # patterns sur N−1
                if not p.confirm:
                    continue                                # déjà couvert par `immediate`
                if uptrend is not None:
                    if p.context == "needs_downtrend" and uptrend:
                        continue
                    if p.context == "needs_uptrend" and not uptrend:
                        continue
                if _confirms(p, conf, patt_bar):
                    confirmed_prev.append(p.name)
                    candidates.append((p.direction, p.strength, p.name))

    if not candidates:
        return {**empty, "pending_confirmation": immediate.get("pending_confirmation", [])}
    best = max(candidates, key=lambda x: x[1])
    return {"direction": best[0], "score": round(best[0] * best[1], 3), "patterns": [best[2]],
            "pending_confirmation": immediate.get("pending_confirmation", []),
            "confirmed_from_prev": confirmed_prev}
