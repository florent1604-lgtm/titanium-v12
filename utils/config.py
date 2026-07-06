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
    _env = Path(__file__).resolve().parent.parent.parent / ".env"
    load_dotenv(_env if _env.exists() else None)
except Exception:
    pass


def _bool(key: str, default: str = "0") -> bool:
    return os.getenv(key, default).strip().lower() in ("1", "true", "yes", "on")

def _int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)))

def _float(key: str, default: float) -> float:
    return float(os.getenv(key, str(default)))

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
]
SCORE_MIN_REQUIRED = _int("SCORE_MIN_REQUIRED", 7)

# ── Overrides par symbole ────────────────────────────��────────────────────────
SYM_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "BTC/USDT": {
        "atr_mult":      _float("BTC_ATR_MULT", 1.0),
        "tp_ratios":     (_float("BTC_TP1", 1.5), _float("BTC_TP2", 2.1), _float("BTC_TP3", 2.6)),
        "rsi_long":      _float("BTC_RSI_LONG", 28.0),
        "rsi_short":     _float("BTC_RSI_SHORT", 72.0),
        "score_min":     _int("BTC_SCORE_MIN", 6),
        "adx_threshold": _float("BTC_ADX_THRESHOLD", 27.0),
        "sl_floor_pct":  _float("BTC_SL_FLOOR_PCT", 0.0010),
    },
    "PAXG/USDT": {
        "atr_mult":      _float("PAXG_ATR_MULT", 1.2),
        "tp_ratios":     (_float("PAXG_TP1", 1.0), _float("PAXG_TP2", 1.5), _float("PAXG_TP3", 2.0)),
        "rsi_long":      _float("PAXG_RSI_LONG", 35.0),
        "rsi_short":     _float("PAXG_RSI_SHORT", 65.0),
        "score_min":     _int("PAXG_SCORE_MIN", 5),
        "adx_threshold": _float("PAXG_ADX_THRESHOLD", 25.0),
        "sl_floor_pct":  _float("PAXG_SL_FLOOR_PCT", 0.0025),
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
    {"atr_mult": 0.6, "tp_ratios": (1.2, 1.8, 2.4), "trailing": False},
    {"atr_mult": 0.8, "tp_ratios": (1.2, 1.8, 2.4), "trailing": False},
    {"atr_mult": 0.8, "tp_ratios": (1.5, 2.1, 2.6), "trailing": False},
    {"atr_mult": 1.0, "tp_ratios": (1.2, 1.8, 2.4), "trailing": False},
    {"atr_mult": 1.0, "tp_ratios": (1.5, 2.1, 2.6), "trailing": False},
    {"atr_mult": 1.2, "tp_ratios": (1.2, 1.8, 2.4), "trailing": False},
    {"atr_mult": 1.2, "tp_ratios": (1.5, 2.1, 2.6), "trailing": False},
    {"atr_mult": 1.3, "tp_ratios": (1.0, 1.5, 2.0), "trailing": False},
    {"atr_mult": 1.3, "tp_ratios": (1.2, 1.8, 2.4), "trailing": False},
    {"atr_mult": 1.5, "tp_ratios": (1.2, 1.8, 2.4), "trailing": False},
    {"atr_mult": 1.5, "tp_ratios": (1.5, 2.1, 2.6), "trailing": False},
]
OPT_CONFIGURATIONS_PAXG = [
    {"atr_mult": 0.8,  "tp_ratios": (0.8, 1.2, 1.6), "trailing": False},
    {"atr_mult": 1.0,  "tp_ratios": (1.0, 1.5, 2.0), "trailing": False},
    {"atr_mult": 1.0,  "tp_ratios": (1.2, 1.8, 2.4), "trailing": False},
    {"atr_mult": 1.2,  "tp_ratios": (1.0, 1.5, 2.0), "trailing": False},
    {"atr_mult": 1.3,  "tp_ratios": (1.2, 1.8, 2.4), "trailing": False},
    {"atr_mult": 1.5,  "tp_ratios": (1.0, 1.5, 2.0), "trailing": False},
]

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

# ── Analyse spectrale (Phase 1 — filtre de régime, cf. CLAUDE.md) ────────────
SPECTRAL_ENABLED         = _bool("SPECTRAL_ENABLED", "1")
SPECTRAL_TF              = _str("SPECTRAL_TF", "30m")       # timeframe d'analyse
SPECTRAL_PMIN            = _int("SPECTRAL_PMIN", 8)          # période cycle min (barres)
SPECTRAL_PMAX            = _int("SPECTRAL_PMAX", 50)         # période cycle max (barres)
SPECTRAL_POWER_THRESHOLD = _float("SPECTRAL_POWER_THRESHOLD", 0.35)

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
PAPER_JOURNAL_FILE     = Path(_str("PAPER_JOURNAL_FILE", "data/paper_journal.json"))
PAPER_JOURNAL_CSV      = Path(_str("PAPER_JOURNAL_CSV", "data/paper_journal.csv"))
PAPER_STATE_FILE       = Path(_str("PAPER_STATE_FILE", "data/paper_state.json"))

# ── Webhook TradingView ────────────────────────────────────────────────────────
WEBHOOK_SECRET  = _str("WEBHOOK_SECRET", "")    # secret partagé (laisser vide = désactivé)
WEBHOOK_ENABLED = _bool("WEBHOOK_ENABLED", "1")

# ── Serveur ─────────────────────────────────────────────────────────────────
UVICORN_HOST      = _str("UVICORN_HOST", "0.0.0.0")
UVICORN_PORT      = _int("UVICORN_PORT", 8080)
UVICORN_LOG_LEVEL = _str("UVICORN_LOG_LEVEL", "info")
LOG_LEVEL         = _str("LOG_LEVEL", "INFO").upper()
