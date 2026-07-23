"""core/portfolio_risk.py — Service de risque portefeuille (R3 rev.2, FAIL-CLOSED).

Consulté AVANT toute ouverture par les moteurs swing et forex. Empêche la
concentration constatée par l'audit (USTECH 47 % + NAS100 47 % = 94 % sur le
même cluster US_INDICES).

Politique FAIL-CLOSED (revue Codex 10/07/2026) : toute entrée non finie et
tout état de position absent, malformé ou illisible REFUSE l'ouverture avec
un motif explicite (`RISK_INPUT_INVALID` / `RISK_STATE_UNAVAILABLE`). Un champ
manquant ne vaut jamais zéro.

Plafonds (dépassement strict bloque ; l'égalité exacte au plafond passe) :
  - par STRATÉGIE (RISK_MAX_STRATEGY_PCT) : gross du moteur demandeur,
    en % de l'equity de CE moteur ;
  - par CLUSTER corrélé (RISK_MAX_CLUSTER_PCT) : gross du cluster tous moteurs,
    en % de l'equity du moteur demandeur ;
  - PORTEFEUILLE : gross (RISK_MAX_GROSS_PCT) et |net| signé (RISK_MAX_NET_PCT),
    en % de l'EQUITY AGRÉGÉE LIVE = somme des equities courantes des moteurs
    présents (swing + forex + crypto paper) — pas des capitaux initiaux
    statiques ; une equity qui fond en drawdown resserre donc les plafonds.
    Les nets par stratégie et par cluster sont calculés et publiés dans
    `exposure_snapshot()` (surveillance) ; le plafond dur net porte sur le
    portefeuille — aux niveaux stratégie/cluster |net| ≤ gross, déjà plafonné.

Unités : swing/forex tiennent leurs notionnels en EUR ; le paper crypto est en
USDT. Approximation documentée : 1 USDT = 1 EUR, légèrement conservatrice avec
EURUSD > 1 (surestime l'exposition crypto, jamais l'inverse).

Paper only : ne bloque que des ouvertures simulées.
"""
from __future__ import annotations

import math
import threading
from typing import Callable, Dict, List, NamedTuple, Tuple

from utils.config import (
    RISK_MAX_CLUSTER_PCT, RISK_MAX_GROSS_PCT, RISK_MAX_NET_PCT,
    RISK_MAX_STRATEGY_PCT,
)

# Clusters d'actifs corrélés (un actif non listé = cluster singleton = lui-même).
CLUSTERS = {
    "US_INDICES": {"USTECH", "NAS100.fs", "NAS100", "US500", "US30", "SPX",
                   "US2000", "DJ30.fs", "S&P.fs", "USTEC"},
    "EU_INDICES": {"EUSTX50.fs", "GER40", "DAX40.fs", "FRA40", "CAC40.fs",
                   "UK100", "FT100.fs", "IT40", "SPA35", "NETH25", "EU50"},
    "ASIA_INDICES": {"HK50", "HSI.fs", "CN50", "CHINA50.fs", "JPN225", "NK225.fs",
                     "AUS200", "SPI200.fs"},
    "GOLD": {"XAUUSD", "XAUEUR", "XAUGBP", "XAUAUD", "XAGUSD", "XPTUSD"},
    "OIL": {"USOIL", "UKOIL", "WTI.fs", "BRENT.fs"},
    "CRYPTO": {"BTCUSD", "ETHUSD", "ETH-USD", "BTC-USD",
               "BTC/USDT", "ETH/USDT", "SOL/USDT", "BTCUSDT", "ETHUSDT",
               "SOLUSDT", "PAXG/USDT", "PAXGUSDT"},
}

_LONG_SIDES = {"long", "buy"}
_SHORT_SIDES = {"short", "sell"}
_PORTFOLIO_LOCK = threading.Lock()
_DEFAULT_CRYPTO_ENGINE = object()


class _Pos(NamedTuple):
    strategy: str
    symbol: str
    signed_eur: float  # + long / − short


def cluster_of(symbol: str) -> str:
    for name, members in CLUSTERS.items():
        if symbol in members:
            return name
    return f"SINGLE:{symbol}"


def _side_sign(side) -> int:
    """+1 long/buy, −1 short/sell, 0 = side invalide (fail-closed chez l'appelant)."""
    s = str(side).strip().lower()
    if s in _LONG_SIDES:
        return 1
    if s in _SHORT_SIDES:
        return -1
    return 0


def _crypto_engine():
    """Moteur paper crypto partagé (None si executor sans moteur, ex. DISABLED).
    Point d'injection pour les tests."""
    from execution.executor import executor
    return getattr(executor, "engine", None)


def _read_engine_positions(strategy: str, table, out: List[_Pos],
                           errors: List[str]) -> None:
    """Lit {sym: {side, notional_eur}} en validant chaque champ. Tout champ
    manquant, non numérique ou non fini est une ERREUR (jamais zéro)."""
    if not isinstance(table, dict):
        errors.append(f"{strategy}: table de positions invalide ({type(table).__name__})")
        return
    for sym, p in table.items():
        try:
            sign = _side_sign(p["side"])
            notional = float(p["notional_eur"])
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"{strategy}:{sym}: side/notional_eur manquant ou invalide ({exc!r})")
            continue
        if sign == 0:
            errors.append(f"{strategy}:{sym}: side inconnu {p.get('side')!r}")
            continue
        if not math.isfinite(notional) or notional < 0:
            errors.append(f"{strategy}:{sym}: notional_eur non fini/négatif ({notional!r})")
            continue
        out.append(_Pos(strategy, str(sym), sign * notional))


def _gather(crypto_engine=_DEFAULT_CRYPTO_ENGINE) -> Tuple[List[_Pos], List[str], Dict[str, float]]:
    """Positions ouvertes signées de TOUS les moteurs (swing + forex + crypto
    paper) et equity LIVE par moteur. Toute erreur collectée fera refuser
    l'ouverture (fail-closed) au lieu d'ignorer silencieusement le moteur."""
    out: List[_Pos] = []
    errors: List[str] = []
    equities: Dict[str, float] = {}

    try:
        from core.swing_engine import swing_state
        _read_engine_positions("swing", swing_state.get("positions"), out, errors)
        equities["swing"] = float(swing_state.get("equity"))
    except Exception as exc:
        errors.append(f"swing: état illisible ({exc!r})")

    try:
        from core.forex_engine import forex_state
        _read_engine_positions("forex", forex_state.get("positions"), out, errors)
        equities["forex"] = float(forex_state.get("equity"))
    except Exception as exc:
        errors.append(f"forex: état illisible ({exc!r})")

    # Crypto paper (PaperExecutor) — approx. documentée 1 USDT = 1 EUR.
    try:
        engine = (_crypto_engine() if crypto_engine is _DEFAULT_CRYPTO_ENGINE
                  else crypto_engine)
        if engine is not None:
            for sym, pos in engine.positions.items():
                sign = _side_sign(getattr(pos, "side", ""))
                notional = float(pos.current_size_usdt())
                if sign == 0 or not math.isfinite(notional) or notional < 0:
                    errors.append(f"crypto:{sym}: side/notionnel invalide")
                    continue
                out.append(_Pos("crypto", str(sym), sign * notional))
            equities["crypto"] = float(engine.equity_with_unrealized())
    except Exception as exc:
        errors.append(f"crypto: état illisible ({exc!r})")

    for name, eq in equities.items():
        if not math.isfinite(eq) or eq <= 0:
            errors.append(f"{name}: equity invalide ({eq!r})")
    return out, errors, equities


def _check_can_open_unlocked(strategy: str, symbol: str, notional_eur: float,
                             equity: float, side: str,
                             crypto_engine=_DEFAULT_CRYPTO_ENGINE) -> Tuple[bool, str]:
    """Autorise (True, 'ok') ou refuse (False, motif) l'ouverture proposée.

    `equity` = equity courante du moteur demandeur (base des plafonds
    stratégie/cluster). Les plafonds portefeuille (gross/net) reposent sur
    l'equity agrégée live de tous les moteurs. FAIL-CLOSED sur toute entrée
    ou tout état invalide.
    """
    # 1) Validation des ENTRÉES — NaN/inf/0/négatif/side inconnu → refus.
    try:
        notional = float(notional_eur)
        eq_engine = float(equity)
    except (TypeError, ValueError):
        return False, "RISK_INPUT_INVALID: notional/equity non numérique"
    sign = _side_sign(side)
    if sign == 0:
        return False, f"RISK_INPUT_INVALID: side inconnu {side!r}"
    if not math.isfinite(notional) or notional <= 0:
        return False, f"RISK_INPUT_INVALID: notional non fini ou ≤ 0 ({notional_eur!r})"
    if not math.isfinite(eq_engine) or eq_engine <= 0:
        return False, f"RISK_INPUT_INVALID: equity moteur non finie ou ≤ 0 ({equity!r})"
    for cap_name, cap in (("RISK_MAX_STRATEGY_PCT", RISK_MAX_STRATEGY_PCT),
                          ("RISK_MAX_CLUSTER_PCT", RISK_MAX_CLUSTER_PCT),
                          ("RISK_MAX_GROSS_PCT", RISK_MAX_GROSS_PCT),
                          ("RISK_MAX_NET_PCT", RISK_MAX_NET_PCT)):
        if not (isinstance(cap, (int, float)) and math.isfinite(float(cap)) and cap > 0):
            return False, f"RISK_INPUT_INVALID: plafond {cap_name} invalide ({cap!r})"

    # 2) État des portefeuilles — la moindre erreur refuse (fail-closed).
    positions, errors, equities = _gather(crypto_engine)
    if errors:
        return False, "RISK_STATE_UNAVAILABLE: " + " ; ".join(errors[:4])

    cl = cluster_of(symbol)
    strat_gross = sum(abs(p.signed_eur) for p in positions if p.strategy == strategy)
    cluster_gross = sum(abs(p.signed_eur) for p in positions if cluster_of(p.symbol) == cl)
    gross_now = sum(abs(p.signed_eur) for p in positions)
    net_now = sum(p.signed_eur for p in positions)

    # Equity agrégée LIVE des moteurs présents (drawdown ⇒ plafonds resserrés).
    equity_total = sum(equities.values())

    strat_cap = eq_engine * RISK_MAX_STRATEGY_PCT / 100.0
    cluster_cap = eq_engine * RISK_MAX_CLUSTER_PCT / 100.0
    gross_cap = equity_total * RISK_MAX_GROSS_PCT / 100.0
    net_cap = equity_total * RISK_MAX_NET_PCT / 100.0

    if strat_gross + notional > strat_cap:
        return False, (f"plafond stratégie {strategy} atteint "
                       f"({(strat_gross + notional):.0f} > {strat_cap:.0f} EUR)")
    if cluster_gross + notional > cluster_cap:
        return False, (f"plafond cluster {cl} atteint "
                       f"({(cluster_gross + notional):.0f} > {cluster_cap:.0f} EUR)")
    if gross_now + notional > gross_cap:
        return False, (f"plafond gross portefeuille atteint "
                       f"({(gross_now + notional):.0f} > {gross_cap:.0f} EUR, "
                       f"equity live {equity_total:.0f})")
    if abs(net_now + sign * notional) > net_cap:
        return False, (f"plafond net portefeuille atteint "
                       f"(|{(net_now + sign * notional):.0f}| > {net_cap:.0f} EUR, "
                       f"equity live {equity_total:.0f})")
    return True, "ok"


def check_can_open(strategy: str, symbol: str, notional_eur: float,
                   equity: float, side: str, *,
                   crypto_engine=_DEFAULT_CRYPTO_ENGINE) -> Tuple[bool, str]:
    """Compatibilité lecture seule ; une ouverture doit utiliser check_and_insert."""
    return _check_can_open_unlocked(
        strategy, symbol, notional_eur, equity, side, crypto_engine,
    )


def check_and_insert(strategy: str, symbol: str, notional_eur: float,
                     equity: float, side: str,
                     insert_fn: Callable[[], None], *,
                     crypto_engine=_DEFAULT_CRYPTO_ENGINE) -> Tuple[bool, str]:
    """Vérifie le risque puis insère atomiquement à l'échelle portefeuille.

    `insert_fn` est synchrone et ne doit contenir aucun `await`. Il n'est appelé
    que si le garde accepte l'ouverture, pendant que le verrou commun aux
    moteurs swing et forex est tenu.
    """
    with _PORTFOLIO_LOCK:
        ok, reason = _check_can_open_unlocked(
            strategy, symbol, notional_eur, equity, side, crypto_engine,
        )
        if not ok:
            return ok, reason
        insert_fn()
        return True, "ok"


def exposure_snapshot() -> dict:
    """Expositions gross + net signées par stratégie, cluster et portefeuille
    (dashboard / diagnostic). `ok=False` + `errors` si un état est illisible —
    dans ce cas check_can_open refuse déjà toute ouverture."""
    positions, errors, equities = _gather()
    by_strategy: Dict[str, Dict[str, float]] = {}
    by_cluster: Dict[str, Dict[str, float]] = {}
    for p in positions:
        s = by_strategy.setdefault(p.strategy, {"gross_eur": 0.0, "net_eur": 0.0})
        s["gross_eur"] += abs(p.signed_eur)
        s["net_eur"] += p.signed_eur
        c = by_cluster.setdefault(cluster_of(p.symbol), {"gross_eur": 0.0, "net_eur": 0.0})
        c["gross_eur"] += abs(p.signed_eur)
        c["net_eur"] += p.signed_eur
    rnd = lambda d: {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in d.items()}
    return {
        "ok": not errors,
        "errors": errors,
        "gross_eur": round(sum(abs(p.signed_eur) for p in positions), 2),
        "net_eur": round(sum(p.signed_eur for p in positions), 2),
        "equity_live_eur": {**{k: round(v, 2) for k, v in equities.items()},
                            "total": round(sum(equities.values()), 2)},
        "by_strategy": rnd(by_strategy),
        "by_cluster": rnd(by_cluster),
        "caps_pct": {"strategy": RISK_MAX_STRATEGY_PCT,
                     "cluster": RISK_MAX_CLUSTER_PCT,
                     "gross": RISK_MAX_GROSS_PCT,
                     "net": RISK_MAX_NET_PCT},
    }
