"""
utils/config.py — Source unique de vérité pour toutes les variables de configuration.
Aucun autre module ne doit appeler os.getenv() directement.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from dotenv import load_dotenv
    _env = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(_env if _env.exists() else None)
except Exception:
    pass


def _bool(key: str, default: str = "0") -> bool:
    return os.getenv(key, default).strip().lower() in ("1", "true", "yes", "on")

def _int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default

def _float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default

def _str(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()

def _list(key: str, default: str = "") -> List[str]:
    return [s.strip() for s in os.getenv(key, default).split(",") if s.strip()]


# ── Symboles ────────────────────────���───────────────────���───────────────────
SYMBOLS: List[str] = _list("BINANCE_SYMBOLS", "BTC/USDT,PAXG/USDT")

# ── Binance REST ─────────────────────────��───────────────────────────────────
REST_BASE     = "https://api.binance.com"
REST_FALLBACK = "https://data-api.binance.vision"
BINANCE_KEY    = _str("BINANCE_KEY")
BINANCE_SECRET = _str("BINANCE_SECRET")

# ── Binance WebSocket ────────────────────────────────────────────────────────
WS_BASES: List[str] = _list(
    "WS_BASES",
    "wss://stream.binance.com:9443,wss://stream.binance.com:443,wss://data-stream.binance.vision"
)

# ── HTTP Pool ─────────────────────────────────────────────────────────────���──
HTTP_POOL_SIZE      = _int("HTTP_POOL_SIZE", 50)
HTTP_CONNECT_LIMIT  = _int("HTTP_CONNECT_LIMIT", 25)
HTTP_TIMEOUT_TOTAL  = _int("HTTP_TIMEOUT_TOTAL", 30)

# ── Futures ───────────────────────────���──────────────────────────────────────
FUTURES_BASE       = _str("FUTURES_BASE", "https://fapi.binance.com")
FUTURES_ENABLED    = _bool("FUTURES_ENABLED", "1")
FUTURES_CACHE_TTL  = _int("FUTURES_CACHE_TTL", 60)
FUTURES_SYMBOLS_MAP: Dict[str, str] = {"BTC/USDT": "BTCUSDT"}

# ── Gold / Twelve Data ─────────────────────────────���─────────────────────────
TWELVEDATA_API_KEY  = _str("TWELVEDATA_API_KEY")
TWELVEDATA_BASE_URL = "https://api.twelvedata.com"
GOLD_REAL_ENABLED   = _bool("GOLD_REAL_ENABLED", "1")
GOLD_CACHE_TTL      = _int("GOLD_CACHE_TTL", 180)
GOLD_SYMBOL_MAP: Dict[str, str] = {"PAXG/USDT": "XAU/USD"}

TD_TF_MAP: Dict[str, str] = {
    "4h": "4h", "2h": "2h", "1h": "1h", "30m": "30min",
    "15m": "15min", "5m": "5min", "3m": "3min", "1m": "1min", "1d": "1day",
}
YF_TF_MAP: Dict[str, str] = {
    "4h": "1h", "2h": "1h", "1h": "1h", "30m": "30m",
    "15m": "15m", "5m": "5m", "3m": "5m", "1m": "1m", "1d": "1d",
}

# ── Delta Volume ─────────────────────────────────────────────────────────────
DELTA_VOL_ENABLED    = _bool("DELTA_VOL_ENABLED", "1")
DELTA_VOL_WINDOW     = _int("DELTA_VOL_WINDOW", 100)
DELTA_VOL_SIGNAL_PCT = _float("DELTA_VOL_SIGNAL_PCT", 0.60)

# ── Candle store ─────────────────────────────────────────────────────────────
MAX_1S          = _int("MAX_1S", 1800)
MAX_CANDLES_30S = _int("MAX_CANDLES_30S", 500)
SCAN_INTERVAL   = _int("SCAN_INTERVAL", 5)
ACTIVE_TF       = _str("ACTIVE_TF", "5m") or "5m"
MIN_DF30_FOR_SCAN = _int("MIN_DF30_FOR_SCAN", 10)

# ── Cache TTL par timeframe ───────────────────��───────────────────────────────
CACHE_TTL: Dict[str, int] = {
    "1m":  _int("M1_CACHE_TTL", 30),
    "3m":  _int("M3_CACHE_TTL", 45),
    "5m":  _int("M5_CACHE_TTL", 60),
    "15m": _int("M15_CACHE_TTL", 90),
    "30m": _int("M30_CACHE_TTL", 120),
    "1h":  _int("H1_CACHE_TTL", 180),
    "2h":  _int("H2_CACHE_TTL", 200),
    "4h":  _int("H4_CACHE_TTL", 240),
    "1d":  _int("D1_CACHE_TTL", 3600),
}
KLINES_LIMIT: Dict[str, int] = {
    "1m": _int("M1_LIMIT", 260),
    "5m": _int("M5_LIMIT", 600),
    "4h": _int("H4_LIMIT", 210),
    "1d": _int("D1_LIMIT", 250),
}

# ── RSI ──────────────────────────────────────────────────────────��───────────
RSI_ENTRY_LONG    = _float("RSI_ENTRY_LONG", 28.0)
RSI_ENTRY_SHORT   = _float("RSI_ENTRY_SHORT", 72.0)
RSI_TF_PRIMARY    = _str("RSI_TF_PRIMARY", "5m")

# ── ADX ───────────────────────────────��───────────────────────────────���──────
ADX_TREND_THRESHOLD = _float("ADX_TREND_THRESHOLD", 27.0)
ADX_VOLATILE_THRESHOLD = _float("ADX_VOLATILE_THRESHOLD", 40.0)

# ── OB/FVG ───────────────────────��──────────────────────────────────────���────
OB_FVG_ATR_MULT     = _float("OB_FVG_ATR_MULT", 0.750)
OB_FVG_PCT_FALLBACK = _float("OB_FVG_PCT_FALLBACK", 0.004)
OB_FVG_FIB_DYNAMIC  = _bool("OB_FVG_FIB_DYNAMIC", "1")
FIB_LEVEL_LOW       = _float("FIB_LEVEL_LOW", 0.618)
FIB_LEVEL_HIGH      = _float("FIB_LEVEL_HIGH", 0.786)
FIB_SWING_LOOKBACK  = _int("FIB_SWING_LOOKBACK", 60)
LIQUIDITY_LOOKBACK  = _int("LIQUIDITY_LOOKBACK", 50)

# ── Scoring ────────────────────────────���─────────────────────────────────────
SCORE_CRITERIA = [
    "EMA200_H4", "STRUCT_H2H1", "OB_FVG_30M", "OB_FVG_15M_CONFIRM",
    "REJET_15M", "TRIX_5M", "ALIGN_H2H1", "EMA200_1D",
    "DELTA_VOL", "LIQ_SWEEP", "ADX_REGIME",
    "RSI_DIVERGENCE", "VOL_SPIKE", "DISPLACEMENT",
    "ORDERBOOK_IMBALANCE", "ORDERBOOK_WALL",
]
SCORE_MIN_REQUIRED = _int("SCORE_MIN_REQUIRED", 8)  # /16 maintenant

# ── Overrides par symbole ────────────────────────────��────────────────────────
SYM_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "BTC/USDT": {
        "atr_mult":      _float("BTC_ATR_MULT", 0.8),
        "tp_ratios":     (_float("BTC_TP1", 2.0), _float("BTC_TP2", 3.0), _float("BTC_TP3", 4.0)),
        "rsi_long":      _float("BTC_RSI_LONG", 28.0),
        "rsi_short":     _float("BTC_RSI_SHORT", 72.0),
        "score_min":     _int("BTC_SCORE_MIN", 7),
        "adx_threshold": _float("BTC_ADX_THRESHOLD", 27.0),
        "sl_floor_pct":  _float("BTC_SL_FLOOR_PCT", 0.0010),
        # Validé walk-forward 70/30 (1h/365j, scripts/backtest_cli.py) le 2026-07-01 :
        # PF out-of-sample 0.80 -> 0.86, maxDD 23.6% -> 13.2%.
        "spectral_regime_filter": _bool("BTC_SPECTRAL_REGIME_FILTER", "1"),
    },
    "PAXG/USDT": {
        "atr_mult":      _float("PAXG_ATR_MULT", 1.0),
        "tp_ratios":     (_float("PAXG_TP1", 1.5), _float("PAXG_TP2", 2.5), _float("PAXG_TP3", 3.5)),
        "rsi_long":      _float("PAXG_RSI_LONG", 35.0),
        "rsi_short":     _float("PAXG_RSI_SHORT", 65.0),
        "score_min":     _int("PAXG_SCORE_MIN", 6),
        "adx_threshold": _float("PAXG_ADX_THRESHOLD", 25.0),
        "sl_floor_pct":  _float("PAXG_SL_FLOOR_PCT", 0.0025),
        # Refusé walk-forward 70/30 (1h/365j, scripts/backtest_cli.py) le 2026-07-01 :
        # PF out-of-sample dégradé 0.94 -> 0.59 — le filtre nuit sur cet actif.
        "spectral_regime_filter": _bool("PAXG_SPECTRAL_REGIME_FILTER", "0"),
    },
}

def get_sym_override(sym: str, key: str, default: Any = None) -> Any:
    return (SYM_OVERRIDES.get(sym) or {}).get(key, default)

# ── Optimisation SL/TP ────────────────────────────��──────────────────────────
OPT_TF             = _str("OPT_TF", "5m")
OPT_IN_SAMPLE_DAYS = _int("OPT_IN_SAMPLE_DAYS", 60)
OPT_OOS_DAYS       = _int("OPT_OOS_DAYS", 20)
OPT_REFRESH_HOURS  = _int("OPT_REFRESH_HOURS", 24)
OPT_MIN_CANDLES    = _int("OPT_MIN_CANDLES", 200)
OPT_FEE_BPS        = _float("OPT_FEE_BPS", 4.0)
OPT_SCORE_CRITERIA = _str("OPT_SCORE_CRITERIA", "combined")
OPT_CONFIGURATIONS = [
    # Configs conservatrices
    {"atr_mult": 0.8, "tp_ratios": (1.5, 2.1, 2.6), "trailing": False},
    {"atr_mult": 1.0, "tp_ratios": (1.5, 2.1, 2.6), "trailing": False},
    {"atr_mult": 1.0, "tp_ratios": (1.2, 1.8, 2.4), "trailing": False},
    # Configs agressives (R/R optimisé)
    {"atr_mult": 0.6, "tp_ratios": (2.0, 3.0, 4.0), "trailing": False},
    {"atr_mult": 0.8, "tp_ratios": (2.0, 3.0, 4.0), "trailing": False},
    {"atr_mult": 0.8, "tp_ratios": (2.5, 3.5, 5.0), "trailing": False},
    {"atr_mult": 1.0, "tp_ratios": (2.0, 3.0, 4.0), "trailing": False},
    {"atr_mult": 1.0, "tp_ratios": (2.5, 3.5, 5.0), "trailing": False},
    # Configs avec trailing (exploite les murs détectés par L2)
    {"atr_mult": 0.8, "tp_ratios": (2.0, 3.0, 4.0), "trailing": True},
    {"atr_mult": 1.0, "tp_ratios": (2.0, 3.0, 4.0), "trailing": True},
    # Zone « respiration » — validée strategy_lab 08/07/2026 (winrate 29→64 %
    # sur BTC 365j quand le SL passe à ATR×2 ; l'ancienne grille plafonnait à
    # ×1.0 et forçait l'optimiseur dans la zone 81 % de sorties SL)
    {"atr_mult": 1.5, "tp_ratios": (1.5, 2.5, 4.0), "trailing": False},
    {"atr_mult": 2.0, "tp_ratios": (1.5, 2.5, 4.0), "trailing": False},
    {"atr_mult": 2.0, "tp_ratios": (2.0, 3.0, 4.0), "trailing": False},
    {"atr_mult": 2.5, "tp_ratios": (1.5, 2.5, 4.0), "trailing": False},
    {"atr_mult": 2.0, "tp_ratios": (1.5, 2.5, 4.0), "trailing": True},
]
OPT_CONFIGURATIONS_PAXG = [
    # Configs conservatrices
    {"atr_mult": 0.8,  "tp_ratios": (1.0, 1.5, 2.0), "trailing": False},
    {"atr_mult": 1.0,  "tp_ratios": (1.2, 1.8, 2.4), "trailing": False},
    # Configs agressives PAXG
    {"atr_mult": 0.8,  "tp_ratios": (1.5, 2.5, 3.5), "trailing": False},
    {"atr_mult": 1.0,  "tp_ratios": (1.5, 2.5, 3.5), "trailing": False},
    {"atr_mult": 1.0,  "tp_ratios": (2.0, 3.0, 4.0), "trailing": False},
    {"atr_mult": 1.2,  "tp_ratios": (1.5, 2.5, 3.5), "trailing": False},
    # Avec trailing
    {"atr_mult": 1.0,  "tp_ratios": (1.5, 2.5, 3.5), "trailing": True},
    # Zone « respiration » PAXG (strategy_lab 08/07/2026)
    {"atr_mult": 1.5,  "tp_ratios": (1.5, 2.5, 3.5), "trailing": False},
    {"atr_mult": 2.0,  "tp_ratios": (1.5, 2.5, 3.5), "trailing": False},
    {"atr_mult": 2.0,  "tp_ratios": (1.2, 1.8, 2.4), "trailing": False},
]

# ── Filtre d'alignement momentum (strategy_lab V3, 08/07/2026) ───────────────
# Bloque un signal pris CONTRE la pente de l'EMA50-H1. Validé : BTC (+31 bps/
# trade, PF 1.59) et forex (PF 1.8-2.0) ; NUISIBLE sur PAXG (−8.7 bps) — d'où
# une liste par symbole. Vide = filtre désactivé.
MOMENTUM_ALIGN_SYMBOLS = _list("MOMENTUM_ALIGN_SYMBOLS", "")

# ── Moteur forex/or MT5-Axi (paper only — stratégie V3 validée 08/07/2026) ──
FOREX_ENABLED         = _bool("FOREX_ENABLED", "0")
FOREX_SYMBOLS         = _list("FOREX_SYMBOLS", "EURUSD,GBPUSD,XAUUSD")
# Surveillés en data seulement (prix affiché, pas de trade) — ex: BTCUSD CFD
# dont le backtest MT5 est non rentable malgré 73 % de winrate.
FOREX_MONITOR_SYMBOLS = _list("FOREX_MONITOR_SYMBOLS", "BTCUSD")
FOREX_SCAN_SECONDS    = _int("FOREX_SCAN_SECONDS", 60)
FOREX_CAPITAL         = _float("FOREX_CAPITAL", 10000.0)   # capital paper virtuel (EUR)
FOREX_RISK_PCT        = _float("FOREX_RISK_PCT", 1.0)      # % du capital risqué par trade
FOREX_SL_ATR          = _float("FOREX_SL_ATR", 2.0)
FOREX_TPS             = [float(x) for x in _list("FOREX_TPS", "1.5,2.5,4.0")]
FOREX_TIME_STOP_HOURS = _int("FOREX_TIME_STOP_HOURS", 48)

# ── Moteur SWING multi-actifs (paper only — configs validées tester natif MT5) ──
# Panier retenu après re-validation fills réels 3,5 ans (docs/RAPPORT_REVALIDATION):
# USTECH +9350€ PF1.66, NAS100.fs +3249€ PF1.84, HSI.fs +383€ PF1.22. Chaque actif
# utilise SA config dans data/asset_configs.json (SL/TP/align/RSI/TF/time-stop).
SWING_ENABLED       = _bool("SWING_ENABLED", "0")
SWING_LIVE_SYMBOLS  = _list("SWING_LIVE_SYMBOLS", "USTECH,NAS100.fs,HSI.fs")
SWING_SCAN_SECONDS  = _int("SWING_SCAN_SECONDS", 30)
SWING_CAPITAL       = _float("SWING_CAPITAL", 10000.0)
SWING_RISK_PCT      = _float("SWING_RISK_PCT", 1.0)

# Forward-paper GELÉ XRP/LINK intraday (Binance) — pré-enreg collab/FORWARD_PAPER_PREREGISTRATION.md.
# MIRROR = miroir des entrées sur le compte démo MT5 (visibilité iOS ; coûts Axi non représentatifs).
FORWARD_PAPER_ENABLED = _bool("FORWARD_PAPER_ENABLED", "0")
FORWARD_PAPER_MIRROR  = _bool("FORWARD_PAPER_MIRROR", "0")
FORWARD_PAPER_SECONDS = _int("FORWARD_PAPER_SECONDS", 3600)

# ── Moteur de CONFLUENCE en DÉMO MT5 (méthode Florent, mode EXPLORE) ──
# Câble la stack de détection (adapter → portes ET) sur l'exécuteur DÉMO MT5 pour
# OUVRIR de vraies positions sur le compte DÉMO et observer les décisions en direct.
# DÉSARMÉ par défaut ; les ordres exigent EN PLUS `DEMO_EXEC_ENABLED=1` + le mur
# démo↔réel (refus absolu hors compte démo). Décision sur bougies CLÔTURÉES.
CONFLUENCE_DEMO_ENABLED = _bool("CONFLUENCE_DEMO_ENABLED", "0")
CONFLUENCE_DEMO_SYMBOLS = _list("CONFLUENCE_DEMO_SYMBOLS", "XAUUSD,EURUSD,US500.fs")
CONFLUENCE_DEMO_LTF     = _str("CONFLUENCE_DEMO_LTF", "M15")
CONFLUENCE_DEMO_HTF     = _str("CONFLUENCE_DEMO_HTF", "H4")
CONFLUENCE_DEMO_SECONDS = _int("CONFLUENCE_DEMO_SECONDS", 300)
# ROTATION d'actifs (directive Florent : « rotation des différents actifs, toutes nos
# ressources »). Le crypto (marché ouvert 24/7) est scanné CHAQUE cycle ; les CFD (univers
# large) tournent par lots de CONFLUENCE_ROTATE_BATCH par cycle (0 = tout à chaque cycle).
CONFLUENCE_ROTATE_BATCH = _int("CONFLUENCE_ROTATE_BATCH", 10)
CONFLUENCE_DEMO_SL_ATR  = _float("CONFLUENCE_DEMO_SL_ATR", 1.5)
CONFLUENCE_DEMO_TP_ATR  = _float("CONFLUENCE_DEMO_TP_ATR", 3.0)
# Ladder de take-profits (multiples d'ATR depuis l'entrée) — méthode Florent (TP1/TP2/TP3).
try:
    CONFLUENCE_DEMO_TP_LADDER = tuple(
        float(x) for x in _list("CONFLUENCE_DEMO_TP_LADDER", "1.5,2.5,4.0"))
except (TypeError, ValueError):
    CONFLUENCE_DEMO_TP_LADDER = (1.5, 2.5, 4.0)
if not CONFLUENCE_DEMO_TP_LADDER:
    CONFLUENCE_DEMO_TP_LADDER = (1.5, 2.5, 4.0)

# ── Confluence CRYPTO (marché 24/7, seul ouvert le week-end) ──
# Décision Florent : MT5 reste la PASSERELLE PRINCIPALE (données + exécution), AJUSTÉE à
# Binance (référence de prix). Le crypto Axi (BTCUSD, ETHUSD…) est LIVE et TRADABLE le
# week-end sur le compte démo → mêmes données MT5 + même exécuteur démo, venue=crypto
# (pas de blocage week-end). Binance sert de cross-check (divergence de prix affichée).
CONFLUENCE_CRYPTO_ENABLED = _bool("CONFLUENCE_CRYPTO_ENABLED", "0")
CONFLUENCE_CRYPTO_SYMBOLS = _list("CONFLUENCE_CRYPTO_SYMBOLS",
                                  "BTCUSD,ETHUSD,XRPUSD,LTCUSD,BCHUSD,ADAUSD")

# ── Module AGRESSIF (phase de test) : setups 4/5 structurés, détectés toujours ──
# `EXEC=1` autorise leur EXÉCUTION sur le démo (tag distinct « confluence-aggr » pour
# comparer strict vs agressif). Détection/alerte toujours actives ; exécution armée à part.
CONFLUENCE_AGGRESSIVE_MIN  = _int("CONFLUENCE_AGGRESSIVE_MIN", 4)
CONFLUENCE_AGGRESSIVE_EXEC = _bool("CONFLUENCE_AGGRESSIVE_EXEC", "0")

# ── Concordance inter-actifs (lead/lag) — recherche EXPLORATOIRE (pré-M2, ne décide rien) ──
# Boucle qui cherche quel actif ANTICIPE quel autre + accumule la persistance ; débrief
# Telegram sur candidat fort+persistant. Crypto = Binance 24/7 (marché ouvert le week-end).
LEADLAG_ENABLED  = _bool("LEADLAG_ENABLED", "0")
LEADLAG_SYMBOLS  = _list("LEADLAG_SYMBOLS",
                         "BTC/USDT,ETH/USDT,XRP/USDT,LTC/USDT,BCH/USDT,ADA/USDT,SOL/USDT,DOGE/USDT,BNB/USDT")
LEADLAG_SECONDS  = _int("LEADLAG_SECONDS", 900)
LEADLAG_MAX_LAG  = _int("LEADLAG_MAX_LAG", 12)
# Timeframes scannés (les liens macro sont souvent plus nets en H1/H4 que sur le M15 bruité).
LEADLAG_TFS      = _list("LEADLAG_TFS", "M15,H1,H4")

# ── EventPlane B0/C0 — MIROIR read-only (fusion Hermes, plan afférent) ──
# Publie les FAITS des moteurs (confluence…) dans core.event_plane. Strictement
# observationnel : aucun ordre, aucun CommandGateway, aucun effet trading (contrat Codex).
EVENTPLANE_MIRROR_ENABLED = _bool("EVENTPLANE_MIRROR_ENABLED", "0")
EVENTPLANE_MIRROR_SECONDS = _int("EVENTPLANE_MIRROR_SECONDS", 300)

# ── Risque portefeuille MT5 (R3 — audit 10/07/2026) ──
# Plafonds d'exposition NOTIONNELLE, en % de l'equity du moteur qui veut ouvrir.
# Vérifiés AVANT toute ouverture (swing + forex). Ex. constaté par l'audit :
# USTECH 47 % + NAS100 47 % = 94 % sur le même cluster US_INDICES → bloqué à 60 %.
RISK_MAX_GROSS_PCT    = _float("RISK_MAX_GROSS_PCT", 150.0)   # toutes positions confondues
RISK_MAX_STRATEGY_PCT = _float("RISK_MAX_STRATEGY_PCT", 90.0) # par moteur (swing / forex)
RISK_MAX_CLUSTER_PCT  = _float("RISK_MAX_CLUSTER_PCT", 60.0)  # par cluster corrélé
RISK_MAX_NET_PCT      = _float("RISK_MAX_NET_PCT", 100.0)     # |net| portefeuille (Σ long − Σ short)

# ── Scan d'opportunités périodique (cron in-app tous les N jours) ──
# Rebalaye tout l'univers MT5, applique une porte de récence (~1 mois) pour
# repérer les actifs qui marchent MAINTENANT, alerte + auto-intègre au moteur
# swing (paper) les nouveaux à fort potentiel. Voir core/opportunity_scan.py.
OPP_SCAN_ENABLED       = _bool("OPP_SCAN_ENABLED", "0")
OPP_SCAN_HOUR_UTC      = _int("OPP_SCAN_HOUR_UTC", 0)      # 00:00 UTC = ouverture Asie (Tokyo)
OPP_PERSIST_DAYS       = _int("OPP_PERSIST_DAYS", 3)       # scans consécutifs avant auto-intégration
OPP_LOOKBACK_DAYS      = _int("OPP_LOOKBACK_DAYS", 30)     # porte de récence
OPP_TOP_N              = _int("OPP_TOP_N", 20)            # deep sur le top N
OPP_MIN_POTENTIAL      = _float("OPP_MIN_POTENTIAL", 150.0)  # seuil "fort potentiel"
OPP_MAX_AUTO_ADD       = _int("OPP_MAX_AUTO_ADD", 5)       # cap auto-intégration
OPP_CHECK_HOURS        = _int("OPP_CHECK_HOURS", 1)        # cadence de vérif du planning

# ── STRICT TRIX ───────────────────────────────────────────────���──────────────
STRICT_TF               = _str("STRICT_TF", "5m")
STRICT_RECALIB_DAYS     = _int("STRICT_RECALIB_DAYS", 2)
STRICT_IN_SAMPLE_DAYS   = _int("STRICT_IN_SAMPLE_DAYS", 60)
STRICT_SUBPERIOD_DAYS   = _int("STRICT_SUBPERIOD_DAYS", 10)
STRICT_ROBUST_MIN       = _int("STRICT_ROBUST_MIN_PERIODS", 2)
STRICT_SHARPE_FLOOR     = _float("STRICT_SHARPE_FLOOR", 0.30)
STRICT_MIN_TRADES       = _int("STRICT_MIN_TRADES", 2)
STRICT_RANDOM_ITERS     = _int("STRICT_RANDOM_ITERS", 150)
STRICT_FEE_BPS          = _float("STRICT_FEE_BPS", 4.0)
STRICT_TOPK_ZONES       = _int("STRICT_TOPK_ZONES", 3)
STRICT_ZONE_MIN_DIST    = _int("STRICT_ZONE_MIN_DIST", 10)

# ── Signal cooling / debounce ─────────────────────────────────────────────────
SIGNAL_COOLDOWN_SEC = _int("SIGNAL_COOLDOWN_SEC", 300)   # 5 min entre 2 signaux même sens

# ── Optimisation OOS ──────────────────────────────────────────────────────────
OPT_MIN_OOS_TRADES = _int("OPT_MIN_OOS_TRADES", 10)      # trades OOS minimum pour valider

# ── Circuit breaker ───────────────────────────────────────────────────────────
CIRCUIT_BREAKER_MAX_DD_PCT   = _float("CIRCUIT_BREAKER_MAX_DD_PCT", 5.0)    # 5% DD max
CIRCUIT_BREAKER_WINRATE_MIN  = _float("CIRCUIT_BREAKER_WINRATE_MIN", 0.30)  # 30% winrate
CIRCUIT_BREAKER_ROLLING_N    = _int("CIRCUIT_BREAKER_ROLLING_N", 20)        # fenêtre 20 trades

# ── Learning ─────────────────────────────────────────────────────────────────
SIGNAL_HISTORY_FILE    = Path(_str("SIGNAL_HISTORY_FILE", "signal_history.json"))
SCORING_WEIGHTS_FILE   = Path(_str("SCORING_WEIGHTS_FILE", "scoring_weights.json"))
LEARNING_REPORT_EVERY  = _int("LEARNING_REPORT_EVERY_SEC", 7200)
LEARNING_MIN_SIGNALS   = _int("LEARNING_MIN_SIGNALS", 10)
LEARNING_ADAPT_RATE    = _float("LEARNING_ADAPT_RATE", 0.05)
LEARNING_TRIGGER_SIGNALS = _int("LEARNING_TRIGGER_SIGNALS", 50)  # adapter tous les 50 signaux
MAX_DD_MULTIPLIER      = _float("MAX_DD_MULTIPLIER", 1.3)

# ── Delta volume ──────────────────────────────────────────────────────────────
DELTA_VOL_USE_NOTIONAL = _bool("DELTA_VOL_USE_NOTIONAL", "1")  # pondérer par prix×qty

# ── Telegram ────────────────────���─────────────────────────────���──────────────
TELEGRAM_BOT_TOKEN       = _str("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_IDS        = _list("TELEGRAM_CHAT_IDS")
TELEGRAM_MIN_INTERVAL    = _int("TELEGRAM_MIN_INTERVAL_SEC", 300)
TELEGRAM_SCORE_THRESHOLD = _float("TELEGRAM_SCORE_THRESHOLD", 7.0)
TELEGRAM_SCORE_LABELS: Dict[int, str] = {
    0: "⚫ Pas de signal", 1: "⚫ Pas de signal", 2: "⚫ Pas de signal",
    3: "🔵 Signal faible", 4: "📡 Surveillance", 5: "📡 Surveillance",
    6: "✅ Bon setup", 7: "🔥 Setup fort", 8: "🚀 Setup optimal",
    9: "💎 Signal premium", 10: "🌟 Setup parfait", 11: "👑 Signal absolu",
}

# Alertes Telegram du MOTEUR DE CONFLUENCE (nouveaux indicateurs : 5 piliers de la
# méthode Florent). Notifie quand ≥ MIN_PILLARS piliers s'alignent (setup en formation)
# ET systématiquement quand une position démo s'ouvre. Anti-spam par symbole.
TELEGRAM_CONFLUENCE_ENABLED     = _bool("TELEGRAM_CONFLUENCE_ENABLED", "1")
TELEGRAM_CONFLUENCE_MIN_PILLARS = _int("TELEGRAM_CONFLUENCE_MIN_PILLARS", 4)
TELEGRAM_CONFLUENCE_INTERVAL    = _int("TELEGRAM_CONFLUENCE_INTERVAL_SEC", 900)

# ── WS Compression ───────────────────────────────────────────────────────────
WS_COMPRESS           = _str("WS_COMPRESS", "off")
WS_COMPRESS_MIN_BYTES = _int("WS_COMPRESS_MIN_BYTES", 25000)
WS_COMPRESS_TYPES     = set(_list("WS_COMPRESS_TYPES", "signal"))

# ── Vision Ollama ─────────────────────────���────────────────────────────��──────
OLLAMA_BASE_URL         = _str("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_CHAT_URL         = f"{OLLAMA_BASE_URL}/api/chat"
VISION_MODEL_PRIMARY    = _str("VISION_MODEL_PRIMARY", "llava")
VISION_MODEL_FALLBACK   = _str("VISION_MODEL_FALLBACK", "llava")
VISION_NUM_CTX          = _int("VISION_NUM_CTX", 2048)
VISION_KEEP_ALIVE       = _str("VISION_KEEP_ALIVE", "3600s")
VISION_TIMEOUT_CONNECT  = _int("VISION_TIMEOUT_CONNECT", 5)
VISION_TIMEOUT_GENERATE = _int("VISION_TIMEOUT_GENERATE", 60)
VISION_CACHE_TTL        = _int("VISION_CACHE_TTL", 300)
VISION_CACHE_SIZE       = _int("VISION_CACHE_SIZE", 32)
VISION_TEXT_ONLY        = _bool("VISION_TEXT_ONLY", "0")

# ── Fundamentals (macro risk scoring) ────────────────────────────────────────
FUNDAMENTALS_ENABLED        = _bool("FUNDAMENTALS_ENABLED", "1")
FUNDAMENTALS_REFRESH_SEC    = _int("FUNDAMENTALS_REFRESH_SEC", 900)   # 15 min
FUNDAMENTALS_RISK_BLOCK     = _float("FUNDAMENTALS_RISK_BLOCK", 70.0) # score > X → cancel
FUNDAMENTALS_RISK_REDUCE    = _float("FUNDAMENTALS_RISK_REDUCE", 30.0)# score > X → réduire
FUNDAMENTALS_ROLLBACK_DELTA = _float("FUNDAMENTALS_ROLLBACK_DELTA", 0.3) # Sharpe delta max
NEWSAPI_KEY                 = _str("NEWSAPI_KEY")
GDELT_ENABLED               = _bool("GDELT_ENABLED", "1")
FUNDAMENTALS_HISTORY_FILE   = Path(_str("FUNDAMENTALS_HISTORY_FILE", "data/risk_history.json"))
FUNDAMENTALS_CONFIG_FILE    = Path(_str("FUNDAMENTALS_CONFIG_FILE", "config/fundamentals.json"))

# ── Trading Mode ─────────────────────────────────────────────────────────────
# "paper" = simulation réaliste (défaut)
# "live"  = exécution Binance réelle (non implémenté)
# "disabled" = signaux seulement, aucune position
TRADING_MODE = _str("TRADING_MODE", "paper")

# ── Paper Trading ─────────────────────────────────────────────────────────────
PAPER_INITIAL_CAPITAL  = _float("PAPER_INITIAL_CAPITAL", 1000.0)    # USDT de départ
PAPER_RISK_PCT         = _float("PAPER_RISK_PCT", 0.02)             # 2% du capital risqué/trade
PAPER_SLIPPAGE_BPS     = _float("PAPER_SLIPPAGE_BPS", 5.0)          # 0.05% de slippage
PAPER_SPREAD_BPS       = _float("PAPER_SPREAD_BPS", 2.0)            # 0.02% de spread (demi)
PAPER_FEE_BPS          = _float("PAPER_FEE_BPS", 4.0)               # 0.04% frais taker
PAPER_FUNDING_RATE_8H  = _float("PAPER_FUNDING_RATE_8H", 0.01)      # 0.01% funding/8h (longs paient)
PAPER_MAX_POSITIONS    = _int("PAPER_MAX_POSITIONS", 3)              # positions simultanées max
PAPER_MAX_EXPOSURE_PCT = _float("PAPER_MAX_EXPOSURE_PCT", 0.60)      # % capital max exposé
PAPER_MAX_AGE_HOURS    = _float("PAPER_MAX_AGE_HOURS", 72.0)         # time-stop: fermeture forcée après N heures (0=désactivé)
PAPER_TRAILING_STOP    = _bool("PAPER_TRAILING_STOP", "0")           # trailing stop activé
PAPER_TRAILING_PCT     = _float("PAPER_TRAILING_PCT", 0.8)           # multiple ATR pour trailing
PAPER_MAX_HOLD_HOURS   = _float("PAPER_MAX_HOLD_HOURS", 48.0)       # fermeture auto si aucun TP en N heures (0=désactivé)
PAPER_JOURNAL_FILE     = Path(_str("PAPER_JOURNAL_FILE", "data/paper_journal.json"))
PAPER_JOURNAL_CSV      = Path(_str("PAPER_JOURNAL_CSV", "data/paper_journal.csv"))
PAPER_STATE_FILE       = Path(_str("PAPER_STATE_FILE", "data/paper_state.json"))

# ── Trade journal "Trading-as-Git" (Phase J, défaut off) ─────────────────────
JOURNAL_STAGING_ENABLED = _bool("JOURNAL_STAGING_ENABLED", "0")
JOURNAL_AUTO_APPROVE    = _bool("JOURNAL_AUTO_APPROVE", "0")
TRADE_JOURNAL_FILE      = Path(_str("TRADE_JOURNAL_FILE", "data/trade_journal.jsonl"))

# ── Event bus typé (Phase E) — passif, sûr par défaut ────────────────────────
EVENT_BUS_ENABLED     = _bool("EVENT_BUS_ENABLED", "1")
EVENT_BUS_MAX_MEMORY  = _int("EVENT_BUS_MAX_MEMORY", 500)
EVENTS_FILE           = Path(_str("EVENTS_FILE", "data/events.jsonl"))

# ── Guard pipeline pré-exécution (Phase G, défaut off pour les guards additionnels) ──
GUARD_CORRELATED_EXPOSURE_ENABLED  = _bool("GUARD_CORRELATED_EXPOSURE_ENABLED", "0")
GUARD_CORRELATED_EXPOSURE_MAX_PCT  = _float("GUARD_CORRELATED_EXPOSURE_MAX_PCT", 0.60)
GUARD_BLACKOUT_ENABLED             = _bool("GUARD_BLACKOUT_ENABLED", "0")
BLACKOUT_EVENTS_FILE               = Path(_str("BLACKOUT_EVENTS_FILE", "config/blackout_events.json"))

# Regroupement des symboles par cluster corrélé (exposition cumulée)
SYM_CLUSTER: Dict[str, str] = {
    "BTC/USDT":  "crypto",
    "PAXG/USDT": "metals",
}

# ── Webhook TradingView ────────────────────────────────────────────────────────
WEBHOOK_SECRET  = _str("WEBHOOK_SECRET", "")    # secret partagé (laisser vide = désactivé)
WEBHOOK_ENABLED = _bool("WEBHOOK_ENABLED", "1")

# ── Order Book L2 ─────────────────────────────────────────────────────────────
ORDERBOOK_L2_ENABLED        = _bool("ORDERBOOK_L2_ENABLED", "1")
ORDERBOOK_SPOT_DEPTH        = _int("ORDERBOOK_SPOT_DEPTH", 100)
ORDERBOOK_FUTURES_DEPTH     = _int("ORDERBOOK_FUTURES_DEPTH", 1000)
ORDERBOOK_WS_UPDATE_MS      = _int("ORDERBOOK_WS_UPDATE_MS", 100)
ORDERBOOK_IMBALANCE_THRESHOLD = _float("ORDERBOOK_IMBALANCE_THRESHOLD", 1.5)
ORDERBOOK_WALL_MULT         = _float("ORDERBOOK_WALL_MULT", 5.0)
ORDERBOOK_HISTORY_SIZE      = _int("ORDERBOOK_HISTORY_SIZE", 30)
ORDERBOOK_FUTURES_WEIGHT    = _float("ORDERBOOK_FUTURES_WEIGHT", 2.0)
ORDERBOOK_CACHE_TTL         = _int("ORDERBOOK_CACHE_TTL", 5)

# Map des symboles futures pour le carnet d'ordres
ORDERBOOK_FUTURES_MAP: Dict[str, str] = {"BTC/USDT": "BTCUSDT"}

# ── Spread tracker ────────────────────────────────────────────────────────────
SPREAD_USE_REALTIME     = _bool("SPREAD_USE_REALTIME", "1")
SPREAD_EMA_WINDOW       = _int("SPREAD_EMA_WINDOW", 30)

# ── Drawdown temps réel ──────────────────────────────────────────────────────
DD_REALTIME_ENABLED     = _bool("DD_REALTIME_ENABLED", "1")
DD_CURVE_INTERVAL_SEC   = _int("DD_CURVE_INTERVAL_SEC", 10)

# ── Serveur ─────────────────────────────────────────────────────────────────
# Sécurité (audit 10/07/2026) : bind LOCAL par défaut. NE PAS remettre 0.0.0.0
# sans authentification — l'API expose des mutations (reset, services, git push).
UVICORN_HOST      = _str("UVICORN_HOST", "127.0.0.1")
UVICORN_PORT      = _int("UVICORN_PORT", 8080)
UVICORN_LOG_LEVEL = _str("UVICORN_LOG_LEVEL", "info")
LOG_LEVEL         = _str("LOG_LEVEL", "INFO").upper()
# Jeton admin pour les routes de MUTATION sensibles. Défaut VIDE = fail-closed
# (toute mutation protégée est refusée tant qu'un jeton n'est pas défini dans .env).
# Ne jamais logguer ni exposer dans l'UI.
ADMIN_TOKEN       = _str("ADMIN_TOKEN", "")

# ── Benchmark de latence multi-plateformes ───────────────────────────────────
LATENCY_SYMBOL          = _str("LATENCY_SYMBOL", "BTC/USDT")
LATENCY_DEFAULT_SECONDS = _int("LATENCY_DEFAULT_SECONDS", 60)
LATENCY_MT5_ENABLED     = _bool("LATENCY_MT5_ENABLED", "0")   # inclure Axi via MetaTrader5
LATENCY_MT5_SYMBOL      = _str("LATENCY_MT5_SYMBOL", "BTCUSD")

# ── Spectral (analyse de cycles — Phase 0) ───────────────────────────────────
SPECTRAL_ENABLED          = _bool("SPECTRAL_ENABLED", "1")
SPECTRAL_TF               = _str("SPECTRAL_TF", "4h")   # timeframe de référence
SPECTRAL_PMIN             = _int("SPECTRAL_PMIN", 8)
SPECTRAL_PMAX             = _int("SPECTRAL_PMAX", 50)
SPECTRAL_POWER_THRESHOLD  = _float("SPECTRAL_POWER_THRESHOLD", 0.30)
SPECTRAL_MIN_BARS         = _int("SPECTRAL_MIN_BARS", 100)  # pmax * 2

# ── Spectral — Phase 1 : filtre de régime dans le scoring (défaut off) ───────
SPECTRAL_REGIME_FILTER       = _bool("SPECTRAL_REGIME_FILTER", "0")
SPECTRAL_CYCLE_CRITERIA      = _list("SPECTRAL_CYCLE_CRITERIA", "TRIX_5M")
SPECTRAL_DEPONDERATION_FACTOR = _float("SPECTRAL_DEPONDERATION_FACTOR", 0.5)
