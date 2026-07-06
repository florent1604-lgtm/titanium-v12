# Titanium Dashboard v10 — Code Map

Generated: 2026-03-29

---

## 1. File Overview

| Property | Value |
|---|---|
| File | `titanium_dashboard_v10.py` |
| Total lines | 5,773 |
| Entry point | `main()` at line 5731 |
| Server | FastAPI + Uvicorn on port 8080 |
| Purpose | Real-time multi-asset crypto trading signal analyzer using SMC (Smart Money Concepts) analysis. Receives live price ticks from Binance WebSocket, resamples to OHLCV, scores multi-timeframe setups across 11 criteria, and pushes signals to browser clients via WebSocket. Includes adaptive ML weighting, walk-forward TRIX optimization, SL/TP backtest optimization, vision AI (Ollama), Telegram alerts, and Gold XAU/USD real data. |

---

## 2. Imports & Dependencies

### Standard Library

| Module | Purpose |
|---|---|
| `asyncio` | Async event loop, task management |
| `base64` | WS gzip+base64 compression encoding |
| `gzip` | WS payload compression |
| `hashlib` | Vision cache key generation (SHA-256) |
| `json` | JSON serialization throughout |
| `logging` | Structured application logging |
| `multiprocessing` | STRICT worker process offload (mode-pro) |
| `os` | Environment variable access |
| `traceback` | Error formatting in scan loop |
| `uuid` | Job ID generation for STRICT worker queue |
| `contextlib.asynccontextmanager` | FastAPI lifespan manager |
| `datetime`, `timezone` | UTC timestamps everywhere |
| `pathlib.Path` | File path handling for persistence files |
| `typing` | Type annotations (Any, Dict, List, Optional, Set, Tuple) |
| `functools.lru_cache` | Imported (not directly used but available) |
| `collections.deque` | Rolling delta volume window (`_delta_vol`) |

### Third-Party

| Package | Import | Purpose |
|---|---|---|
| `aiohttp` | `aiohttp` | Async HTTP client, WebSocket client to Binance |
| `numpy` | `np` | Vectorized array math for backtests, drawdown, ATR |
| `pandas` | `pd` | OHLCV DataFrames, resampling, index ops |
| `pandas_ta` | `ta` | Technical indicators: ATR, EMA, RSI, ADX, Supertrend, TRIX |
| `uvicorn` | `uvicorn` | ASGI server to run FastAPI |
| `fastapi` | `FastAPI`, `HTTPException`, `WebSocket`, `WebSocketDisconnect`, `Request` | REST API, WebSocket endpoints |
| `fastapi.responses` | `HTMLResponse` | Serve dashboard HTML |
| `starlette.middleware.gzip` | `GZipMiddleware` | HTTP response compression (>1500 bytes) |
| `numba` | `jit`, `prange` | Optional JIT compilation for numeric loops (graceful fallback) |
| `psutil` | `psutil` | Optional CPU/RAM monitoring for STRICT worker processes |
| `dotenv` | `load_dotenv` | Load `.env` configuration file |

---

## 3. Configuration Constants

All constants are loaded from environment variables via `os.getenv()` with defaults.

| Line range | Section | Key constants |
|---|---|---|
| 123–128 | Symbols & WebSocket URLs | `SYMBOLS`, `WS_BASE`, `WS_BASES`, `REST_BASE`, `REST_FALLBACK` |
| 131–133 | HTTP pool | `HTTP_POOL_SIZE` (50), `HTTP_CONNECT_LIMIT` (25), `HTTP_TIMEOUT_TOTAL` (30) |
| 138–139 | Binance API keys | `BINANCE_KEY`, `BINANCE_SECRET` |
| 144–152 | Futures | `FUTURES_BASE`, `FUTURES_ENABLED`, `FUTURES_CACHE_TTL`, `FUTURES_SYMBOLS_MAP` |
| 167–190 | Gold / XAU/USD | `TWELVEDATA_API_KEY`, `TWELVEDATA_BASE_URL`, `GOLD_REAL_ENABLED`, `GOLD_CACHE_TTL`, `GOLD_SYMBOL_MAP`, `_TD_TF_MAP`, `_YF_TF_MAP` |
| 195–198 | Delta Volume | `DELTA_VOL_ENABLED`, `DELTA_VOL_WINDOW` (100), `DELTA_VOL_SIGNAL_PCT` (0.60) |
| 203–232 | Scoring & FVG/OB | `USE_1D_BIAS`, `D1_CACHE_TTL`, `SCAN_INTERVAL`, `ACTIVE_TF`, `OB_FVG_ATR_MULT` (0.75), `OB_FVG_FIB_DYNAMIC`, `FIB_LEVEL_LOW` (0.618), `FIB_LEVEL_HIGH` (0.786), `FIB_SWING_LOOKBACK` |
| 239–242 | RSI thresholds | `RSI_ENTRY_LONG` (28), `RSI_ENTRY_SHORT` (72) |
| 258–292 | Per-symbol overrides | `SYM_OVERRIDES` dict (PAXG special params), `OPT_CONFIGURATIONS_PAXG` |
| 309–329 | Optimization Module 18 | `OPT_YEAR`, `OPT_REFRESH_HOURS` (24), `OPT_IN_SAMPLE_DAYS` (60), `OPT_FEE_BPS` (4), `OPT_SCORE_CRITERIA`, `OPT_TF`, `OPT_CONFIGURATIONS` (7 configs) |
| 337–350 | Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS`, `TELEGRAM_MIN_INTERVAL_SEC`, `TELEGRAM_SCORE_THRESHOLD` (6) |
| 393–401 | WS compression & cache TTLs | `WS_COMPRESS`, `WS_COMPRESS_MIN_BYTES`, `H4_CACHE_TTL`, `M1_CACHE_TTL`, `M5_CACHE_TTL` |
| 411–439 | STRICT TRIX | `STRICT_TF`, `STRICT_RECALIB_DAYS` (120), `STRICT_IN_SAMPLE_DAYS` (120), `STRICT_MAX_BARS`, `STRICT_RANDOM_ITERS` (300), `STRICT_FEE_BPS`, `STRICT_SHARPE_FLOOR` (0.30), `STRICT_SUBPERIOD_DAYS`, `STRICT_OFFLOAD_PROCESS` |
| 454–465 | V8 module params | `LIQUIDITY_LOOKBACK` (50), `ADX_TREND_THRESHOLD` (27.0), `MAX_DD_MULTIPLIER` (1.3), `SCORE_MIN_REQUIRED` (7), `CB_CHECK_INTERVAL` (3600) |
| 477–479 | Candle persistence | `CANDLE_PERSIST`, `CANDLE_PERSIST_EVERY_SEC`, `CANDLE_PERSIST_FILE` |
| 583–597 | Learning Module 4 | `SIGNAL_HISTORY_FILE`, `SCORING_WEIGHTS_FILE`, `LEARNING_REPORT_EVERY`, `LEARNING_MIN_SIGNALS`, `LEARNING_ADAPT_RATE`, `SCORE_CRITERIA` (list of 11) |
| 1019–1039 | Vision (Ollama) | `OLLAMA_BASE_URL`, `OLLAMA_CHAT_URL`, `VISION_MODEL_PRIMARY`, `VISION_MODEL_FALLBACK`, `VISION_NUM_CTX`, `VISION_KEEP_ALIVE`, `VISION_TIMEOUT_PRIMARY` (420s), `VISION_TIMEOUT_FALLBACK` (120s), `VISION_TEXT_ONLY`, `VISION_CACHE_TTL`, `VISION_CACHE_SIZE` |

---

## 4. Classes

### `TitaniumOptimizerV8` — line 612

**Purpose:** Static utility class for SMC v8 signals: liquidity sweep detection and ADX regime classification.

| Method | Line | Signature | Description |
|---|---|---|---|
| `detect_liquidity_sweep` | 625 | `(df, side) -> bool` | Detects institutional stop hunt: recent wick pierces historical extreme then closes back above/below with 0.3% margin |
| `get_market_regime` | 670 | `(df) -> str` | Returns `"TREND"` / `"RANGE"` / `"UNKNOWN"` based on ADX14 vs `ADX_TREND_THRESHOLD` |

---

### `VisionCache` — line 1098

**Purpose:** LRU cache with TTL for Ollama vision analysis results, keyed by SHA-256 hash of (image_b64 prefix + symbol + timeframe).

| Method | Line | Signature | Description |
|---|---|---|---|
| `__init__` | 1099 | `(max_size, ttl_s)` | Initialize cache store, order list, hit/miss counters |
| `make_key` | 1107 | `(image_b64, symbol, timeframe) -> str` (static) | SHA-256 hash for cache key |
| `get` | 1112 | `(key) -> Optional[dict]` | Retrieve entry if not expired; updates hit/miss counters |
| `set` | 1135 | `(key, value)` | Store entry; evict oldest when over max_size |
| `stats` | 1146 | `() -> dict` | Returns size, ttl, hits, misses, hit_rate |

---

## 5. Functions by Category

### 5.1 Data Fetching Functions

| Function | Line | Signature | Description |
|---|---|---|---|
| `fetch_klines` | 3078 | `(session, sym, interval, limit) -> pd.DataFrame` | Binance REST `/api/v3/klines` with primary+fallback base URL, returns OHLCV DataFrame |
| `_get_cached` | 3144 | `(session, sym, interval) -> pd.DataFrame` | Unified TTL-cache helper; checks `_CACHE_REGISTRY` before calling `fetch_klines` |
| `get_h4_cached` | 3155 | `(session, sym) -> pd.DataFrame` | 4H klines with 240s TTL, limit 500 |
| `get_h2_cached` | 3156 | `(session, sym) -> pd.DataFrame` | 2H klines with 240s TTL, limit 400 |
| `get_h1_cached` | 3157 | `(session, sym) -> pd.DataFrame` | 1H klines with 120s TTL, limit 500 |
| `get_m30_cached` | 3158 | `(session, sym) -> pd.DataFrame` | 30m klines with 90s TTL, limit 500 |
| `get_m15_cached` | 3159 | `(session, sym) -> pd.DataFrame` | 15m klines with 60s TTL, limit 500 |
| `get_m5_cached` | 3160 | `(session, sym) -> pd.DataFrame` | 5m klines with 60s TTL, limit 1000 |
| `get_m3_cached` | 3161 | `(session, sym) -> pd.DataFrame` | 3m klines with 20s TTL, limit 150 |
| `get_m1_cached` | 3162 | `(session, sym) -> pd.DataFrame` | 1m klines with 30s TTL, limit 500 |
| `get_1d_cached` | 3163 | `(session, sym) -> pd.DataFrame` | Daily klines with 3600s TTL, limit 250 |
| `fetch_klines_history` | 3708 | `(session, sym, interval, days) -> pd.DataFrame` | Paginated multi-page historical fetch for N days; retries 3x per page; deduplicates index |
| `fetch_futures_metrics` | 3169 | `(session, sym) -> dict` | Fetches OI, OI history, funding rate, mark price, long/short ratio from Binance Futures; 60s cache |
| `fetch_gold_candles` | 3430 | `(session, interval, count) -> pd.DataFrame` | Dual-provider Gold fetch: Twelve Data primary, Yahoo Finance fallback; 180s cache |
| `_fetch_twelvedata` | 3285 | `(session, symbol, interval, outputsize) -> pd.DataFrame` | Twelve Data REST `/time_series` for XAU/USD |
| `_fetch_yahoo_gold` | 3334 | `(session, interval, count) -> pd.DataFrame` | Yahoo Finance `/v8/finance/chart/GC=F` for Gold Futures with resample for 4h/2h |
| `_parse_twelvedata_df` | 3261 | `(data) -> pd.DataFrame` | Parse Twelve Data JSON response into OHLCV DataFrame |
| `create_optimized_session` | 3105 | `() -> aiohttp.ClientSession` | Creates aiohttp session with TCPConnector pool (50 total, 25/host), 300s DNS cache |

---

### 5.2 Signal / Indicator Functions

| Function | Line | Signature | Description |
|---|---|---|---|
| `compute_ema200` | 1310 | `(series) -> float` | EMA(200) on a pandas Series, returns last value |
| `_detect_market_structure` | 1317 | `(df, n=20) -> str` | BOS detection on N last candles: identifies pivot highs/lows, validates by close and displacement > 0.5 ATR. Returns `"BULLISH"` / `"BEARISH"` / `"RANGING"` |
| `_detect_rejection_candle` | 1398 | `(df, side) -> bool` | Detects pin bar, engulfing, or strong body candle aligned with trade side |
| `_compute_fib_tolerance` | 1435 | `(df, price, atr_val) -> float` | Calculates dynamic tolerance from Fibonacci zone [0.618, 0.786] of last swing; falls back to ATR × mult |
| `_ob_status` | 1465 | `(df, ob_top, ob_bot, side, lookback_after=20) -> str` | Classifies OB as `"intact"` / `"tested"` / `"broken"` based on subsequent price action |
| `_detect_range_30m` | 1497 | `(df_m30, lookback=20) -> bool` | Returns True if current ATR < 30% of mean ATR over lookback (range/consolidation filter) |
| `_has_ob_or_fvg_alignment` | 1516 | `(df, side, price, lookback=50) -> Tuple[bool, str, float]` | Checks if price is near an OB or FVG; returns (aligned, ob_status, quality 0-1). FVG-in-OB raises quality ×1.2 |
| `detect_fvg` | 2595 | `(df30, n=200) -> List[dict]` | Detects all Fair Value Gaps (bull: h0 < l2; bear: l0 > h2) on last N candles; returns list of {top, bot, ts, type, width_pct} |
| `detect_ob` | 2628 | `(df30, side, n=60) -> List[dict]` | Detects up to 5 Order Blocks with intact/tested/broken status |
| `detect_candle_patterns` | 2660 | `(df30, n=40) -> List[dict]` | 17-pattern library (Doji, Marubozu, Hammer, Shooting Star, Engulfing, Harami, Morning/Evening Star, Three White Soldiers, Three Black Crows, Tweezer Top/Bottom, Piercing Line, Dark Cloud Cover, Bull/Bear Kicker, Three Inside Up/Down) |
| `detect_reversal_candles` | 2823 | `(df30, lookback=300) -> List[dict]` | Scans for reversal patterns over lookback candles for chart highlighting |
| `compute_volume_poc` | 2900 | `(df30, bins=24, lookback=120) -> dict` | Volume-weighted Point of Control using histogram binning |
| `compute_supertrend` | 2919 | `(df30) -> dict` | Supertrend(10, 3.0) via pandas_ta; returns {direction, value} |
| `_update_delta_vol` | 3473 | `(sym, price, qty, is_buyer_maker) -> None` | Updates rolling delta volume for a symbol from an aggTrade event |
| `_ma` | 3509 | `(s, length, ma_type) -> pd.Series` | EMA or SMA helper for STRICT TRIX |
| `_trix_line` | 3516 | `(close, length) -> pd.Series` | TRIX = ROC(EMA(EMA(EMA(close)))) in % |
| `strict_trix_apply` | 3525 | `(df, params) -> pd.DataFrame` | Applies STRICT TRIX indicator: adds trix, trix_signal, trix_hist, trend_ma, entry_long, exit_long columns |
| `strict_trix_backtest_sharpe` | 3554 | `(df, params, fee_bps=4.0) -> dict` | Long-only TRIX backtest; returns {trades, return, sharpe, max_dd} |
| `_rand_params` | 3597 | `(rng) -> dict` | Generates random TRIX parameter set (trix_len 5-51, signal_len 5-51, trend_ma_len 100-800) |

---

### 5.3 Scoring Functions

| Function | Line | Signature | Description |
|---|---|---|---|
| `score_setup` | 1604 | `(df_h4, df_1m, df30, df_h2, df_h1, df_m30, df_m15, df_m5, strict_params, scoring_w, rsi_long_override, rsi_short_override, df_1d, delta_vol_state, futures_data, active_tf) -> Tuple[int, str, List[str], dict]` | Core 11-point SMC scorer. Returns (score, side, confirmations, algo_context). Evaluates EMA200_H4, STRUCT_H2H1, OB_FVG_30M, OB_FVG_15M_CONFIRM, REJET_15M, TRIX_5M, ALIGN_H2H1, EMA200_1D, DELTA_VOL, LIQ_SWEEP, ADX_REGIME |
| `get_sym_override` | 294 | `(sym, key, default=None) -> Any` | Returns per-symbol override value from `SYM_OVERRIDES` or global default |
| `_compute_learning_report` | 874 | `(sym) -> dict` | Computes per-criterion win rate and suggested weight adjustments for adaptive learning |

---

### 5.4 Backtest / Optimization Functions

| Function | Line | Signature | Description |
|---|---|---|---|
| `filter_year` | 1996 | `(df, year=OPT_YEAR) -> Optional[pd.DataFrame]` | Filters DataFrame to a calendar year |
| `_backtest_strategy_real` | 2007 | `(df, config, fee_bps) -> dict` | Vectorized EMA200 entry/exit backtest; computes sharpe, expectancy, winrate, max_drawdown, trades, return |
| `_opt_score` | 2179 | `(res, criteria) -> float` | Composite optimization score: sharpe only / expectancy only / combined (0.5×Sharpe + 0.3×Exp + 0.2×(1+DD)) |
| `_run_optimisation_sync` | 2196 | `(symbols, candle_store_snap, configurations, year) -> dict` | CPU-intensive sync optimization loop for multiple symbols and configs; returns best config per symbol |
| `compute_adaptive_levels` | 2463 | `(entry_price, atr, side, lookback_df, atr_mult=1.0, tp_ratios=(1.2,1.8,2.4), fee_bps=4) -> Tuple[float, List[float]]` | ATR-clamped (p20-p80) SL/TP calculation with Binance fee adjustment; returns (sl, [tp1, tp2, tp3]) |
| `compute_atr_levels` | 2519 | `(df30, side, df_m3, fvgs, obs) -> Tuple[float, float, List[float]]` | Legacy entry/SL/TPs using swing extremes + OB levels; returns (entry, sl, [tp1..tp4]) |
| `_split_periods` | 3611 | `(df, subperiod_days) -> list[pd.DataFrame]` | Splits DataFrame into chronological sub-periods for walk-forward robustness testing |
| `_robust_score` | 3638 | `(sharpes, floor, min_periods) -> float` | Robustness score: mean - 0.35×std + 0.25×pass_ratio; requires min_periods above floor |
| `_gaussian_blur2d` | 3653 | `(mat) -> np.ndarray` | 5×5 Gaussian blur on heatmap (no scipy) for smoothing the TRIX parameter grid |
| `_pick_zone_centers` | 3680 | `(score_smoothed, topk, min_dist) -> list` | Non-maximum suppression: picks top-K grid centers with minimum distance separation |
| `_compute_strict_zones_for_symbol` | 3813 | `(df, periods, progress_hook=None) -> dict` | CPU-heavy STRICT heatmap computation: random search over TRIX params, multi-period robustness, 4-tier fallback (strict / relaxed / ultra-relaxed / best-effort) |

---

### 5.5 WebSocket / API Handlers

| Function | Line | Signature | Description |
|---|---|---|---|
| `ws_binance` | 2936 | `(session) -> None` (async) | Binance aggTrade WebSocket stream; updates delta volume and builds 1s OHLCV buckets; reconnects across WS_BASES with heartbeat |
| `resample_and_push` | 3048 | `(sym) -> None` (async) | Resamples raw_1s ticks to 30s OHLCV; stores in candle_store; broadcasts candle update to WS clients |
| `broadcast` | 4914 | `(sym, payload) -> None` (async) | Sends payload to all WebSocket clients for a symbol; handles optional gzip+base64 compression; tracks dead connections |
| `_ws_pack` | 4876 | `(payload) -> str` | Serializes payload to JSON string, optionally compresses with gzip+base64 if `WS_COMPRESS=gzip_base64` and size threshold met |
| `_ollama_chat` | 1159 | `(session, model, user_text, image_b64, timeout_s) -> str` (async) | Single Ollama `/api/chat` POST; raises RuntimeError on error or empty response |
| `ollama_vision_analyze` | 1193 | `(session, image_b64, symbol, timeframe, price, side_hint, algo_context) -> dict` (async) | Full vision analysis with 3-tier fallback: primary model → fallback model → text-only; uses VisionCache |
| `telegram_send` | 354 | `(session, text, symbol, force) -> None` (async) | Sends Telegram message to all configured chat IDs; throttles by symbol with `TELEGRAM_MIN_INTERVAL_SEC` |

---

### 5.6 Utility Functions

| Function | Line | Signature | Description |
|---|---|---|---|
| `rest_sym` | 467 | `(s) -> str` | Converts `"BTC/USDT"` to `"BTCUSDT"` for REST params |
| `ws_sym` | 470 | `(s) -> str` | Converts `"BTC/USDT"` to `"btcusdt"` for WS stream names |
| `_normalize_sym` | 4014 | `(sym) -> str` | Normalizes symbol string (uppercase, `_` to `/`) |
| `_sym_ui_to_binance` | 5188 | `(sym_ui) -> str` | Converts UI symbol format to Binance REST format |
| `_interval_to_binance` | 5193 | `(interval) -> str` | Validates and returns interval string for Binance API |
| `_fetch_start_ms` | 3703 | `(days) -> int` | Returns UNIX timestamp in ms for N days ago |
| `_fetch_interval_minutes` | 3721 | `(iv) -> float` (inner) | Parses interval string (e.g. `"5m"`, `"4h"`, `"1d"`) to minutes |
| `_strip_data_url` | 1056 | `(b64) -> str` | Strips data URL prefix from base64 image string |
| `_extract_json_block` | 1064 | `(text) -> str` | Extracts raw JSON from model response, stripping markdown fences |
| `_empty_vision` | 1079 | `(reason) -> dict` | Returns a neutral/empty vision result dict with error context |
| `_client_counts` | 4910 | `() -> dict` | Returns total and per-symbol WebSocket client counts |
| `_load_learning_state` | 699 | `() -> None` | Loads signal_history and scoring_weights from JSON files at startup |
| `_save_learning_state` | 722 | `() -> None` | Persists signal_history and scoring_weights to JSON files |
| `_persist_candle_store_if_needed` | 482 | `() -> None` (async) | Optionally serializes candle_store to JSON every N seconds |
| `record_signal_outcome` | 738 | `(sym, entry, sl, tp1, current_price, ts_signal, confs, score, side) -> None` | Updates outcome of pending signals (tp1/2/3/4_hit, sl_hit) and computes PnL |
| `update_trailing_be` | 798 | `(sym, current_price) -> bool` | Moves SL to break-even when TP1 is hit; flags `BE_ACTIVATED_TP1` in confirmations |
| `add_signal_to_history` | 848 | `(sym, score, side, confs, entry, sl, tps) -> None` | Appends new pending signal to signal_history (capped at 500) |

---

### STRICT Mode-Pro Worker Functions

| Function | Line | Signature | Description |
|---|---|---|---|
| `_strict_enqueue` | 4017 | `(sym, job_q) -> dict` (async) | Enqueues a STRICT recalibration job into the multiprocessing queue |
| `strict_worker_main` | 4159 | `(job_q, res_q)` | Entry point for the worker subprocess: fetches history, splits periods, runs `_compute_strict_zones_for_symbol`, sends result back via res_q |
| `strict_recalibrate_symbol` | 4233 | `(session, sym) -> dict` (async) | One-shot STRICT recalibration for a single symbol (non-blocking via asyncio.to_thread) |

---

## 6. External API Calls

### Binance REST API (`https://api.binance.com`, fallback: `https://data-api.binance.vision`)

| Endpoint | Used in | Purpose |
|---|---|---|
| `GET /api/v3/klines` | `fetch_klines()` (line 3078) | OHLCV candles for all timeframes |
| `GET /api/v3/klines` (paginated) | `fetch_klines_history()` (line 3708) | Historical klines for STRICT/OPT backtests |
| `GET /api/v3/klines` | `api_klines()` route (line 5200) | Frontend multi-TF chart data |

### Binance Futures REST API (`https://fapi.binance.com`)

| Endpoint | Used in | Purpose |
|---|---|---|
| `GET /fapi/v1/openInterest` | `fetch_futures_metrics()` (line 3194) | Current open interest |
| `GET /futures/data/openInterestHist` | `fetch_futures_metrics()` (line 3205) | OI history (2 periods, 5m) for OI change % |
| `GET /fapi/v1/premiumIndex` | `fetch_futures_metrics()` (line 3221) | Funding rate and mark price |
| `GET /futures/data/globalLongShortAccountRatio` | `fetch_futures_metrics()` (line 3233) | Long/short account ratio |

### Binance WebSocket (`wss://stream.binance.com:9443`, `:443`, `wss://data-stream.binance.vision`)

| Stream | Used in | Purpose |
|---|---|---|
| `{sym}@aggTrade` (combined streams) | `ws_binance()` (line 2936) | Live price ticks + aggTrade for delta volume (is_buyer_maker field) |

### Ollama Local Vision AI (`http://localhost:11434`)

| Endpoint | Used in | Purpose |
|---|---|---|
| `POST /api/chat` | `_ollama_chat()` (line 1159) | LLaVA/Qwen2.5-VL vision + text analysis for chart interpretation |

### Twelve Data (`https://api.twelvedata.com`)

| Endpoint | Used in | Purpose |
|---|---|---|
| `GET /time_series` | `_fetch_twelvedata()` (line 3285) | XAU/USD OHLCV candles (primary Gold provider) |
| `GET /api_usage` | `get_gold_status()` route (line 5710) | Check API credit usage |

### Yahoo Finance (no key required)

| Endpoint | Used in | Purpose |
|---|---|---|
| `GET https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF` | `_fetch_yahoo_gold()` (line 3334) | Gold Futures (GC=F) OHLCV as fallback for XAU/USD |

### Telegram Bot API (`https://api.telegram.org`)

| Endpoint | Used in | Purpose |
|---|---|---|
| `POST /bot{token}/sendMessage` | `telegram_send()` (line 354) | Signal alerts and learning reports with HTML formatting |

---

## 7. Background Tasks / Async Loops

All tasks are created in the `lifespan` context manager (line 4948) and cancelled on shutdown.

| Task | Function | Line | Interval | Purpose |
|---|---|---|---|---|
| Binance WS | `ws_binance(session)` | 2936 | Continuous | Receives aggTrade stream, updates 1s OHLCV buckets and delta volume |
| Scan Loop | `scan_loop(session)` | 4437 | `SCAN_INTERVAL` (5s) | Main loop: fetches all TFs, scores setups, broadcasts signals |
| Learning Report | `learning_report_loop(session)` | 941 | `LEARNING_REPORT_EVERY` (2h) | Computes adaptive weight suggestions, sends Telegram report |
| Optimization | `optimisation_loop()` | 2370 | `OPT_REFRESH_HOURS` (24h) | Runs multi-asset SL/TP backtest optimization via `asyncio.to_thread` |
| Circuit Breaker | `circuit_breaker_monitor()` | 2394 | `CB_CHECK_INTERVAL` (3600s) | Monitors real drawdown vs backtest; triggers forced recalibration if exceeded |
| STRICT Recalib (default mode) | `strict_recalib_loop(session)` | 4303 | `STRICT_RECALIB_DAYS` (120d) | Walk-forward TRIX parameter optimization per symbol via `asyncio.to_thread` |
| STRICT Scheduler (mode-pro) | `strict_scheduler_loop(job_q)` | 4045 | 10s polling | Enqueues recalibration jobs for STRICT worker processes; includes watchdog |
| STRICT Result Listener (mode-pro) | `strict_result_listener(res_q)` | 4090 | Continuous | Receives results from worker processes and updates `_strict_store` |

---

## 8. FastAPI Routes

| Method | Path | Handler Function | Line | Description |
|---|---|---|---|---|
| `GET` | `/` | `index()` | 5019 | Serves `titanium_dashboard.html` static file |
| `GET` | `/api/state` | `get_state()` | 5026 | Full app state: signals, weights, learning, STRICT store, optimization results, active TF |
| `POST` | `/api/set_tf` | `set_active_tf(req)` | 5056 | Change active timeframe at runtime; broadcasts `tf_change` event to all WS clients |
| `GET` | `/api/learning/report` | `learning_report_all()` | 5088 | Learning performance report for all symbols |
| `GET` | `/api/learning/report/{symbol}` | `learning_report_symbol(symbol)` | 5096 | Learning report for a specific symbol |
| `POST` | `/api/learning/confirm/{symbol}` | `learning_confirm(symbol, req)` | 5104 | Apply or reject suggested scoring weight changes |
| `GET` | `/api/learning/weights` | `learning_weights()` | 5160 | Current adaptive scoring weights per symbol |
| `POST` | `/api/learning/reset/{symbol}` | `learning_reset(symbol)` | 5165 | Reset weights to 1.0 for a symbol |
| `GET` | `/api/learning/history/{symbol}` | `learning_history(symbol)` | 5175 | Last 100 signal outcomes for a symbol |
| `GET` | `/api/klines/{symbol}/{interval}/{limit}` | `api_klines(symbol, interval, limit, req)` | 5200 | Live klines + EMA20 for frontend chart rendering |
| `GET` | `/api/optim/results` | `optim_results()` | 5251 | Full optimization results with all_results list (top-6 configs per symbol) |
| `GET` | `/api/optim/results/{symbol}` | `optim_results_symbol(symbol)` | 5268 | Optimization result for a specific symbol |
| `POST` | `/api/optim/run` | `optim_run(req)` | 5285 | Trigger optimization in background; returns immediately |
| `GET` | `/api/health` | `api_health()` | 5325 | Health check: tick age, bar age, signal presence, WS client count |
| `GET` | `/api/metrics` | `metrics()` | 5337 | WS stats: messages sent, bytes, broadcast timestamps |
| `GET` | `/api/strict/heatmap/{symbol}` | `strict_heatmap(symbol)` | 5348 | STRICT TRIX parameter heatmap (compressed by GZipMiddleware) |
| `GET` | `/api/strict/status/{symbol}` | `strict_status(symbol)` | 5365 | STRICT job status: running/pending, duration, job_id, params |
| `GET` | `/api/strict/workers` | `strict_workers_status(req)` | 5397 | Worker process list (mode-pro): pid, alive status, pending/running symbols |
| `GET` | `/api/strict/monitor` | `strict_monitor(req)` | 5412 | Full STRICT monitoring: workers CPU/RAM (psutil), per-symbol phase/progress/duration |
| `POST` | `/api/strict/recalibrate/{symbol}` | `strict_recalibrate(symbol, req)` | 5487 | Trigger STRICT recalibration: enqueue (mode-pro) or async task (default mode) |
| `WS` | `/ws/{symbol}` | `ws_endpoint(websocket, symbol)` | 5517 | WebSocket endpoint: sends current signal on connect, then streams updates |
| `POST` | `/api/push` | `receive_push(req)` | 5535 | External bridge: injects signal/candle/log payloads (disabled by default) |
| `POST` | `/api/vision/analyze` | `vision_analyze(req)` | 5564 | Ollama vision analysis: accepts image_b64 + algo_context, broadcasts result |
| `GET` | `/api/vision/health` | `vision_health()` | 5622 | Vision system status: model names, cache stats, Ollama URL |
| `GET` | `/api/futures` | `get_futures()` | 5639 | Futures metrics for all configured symbols (OI, funding, mark price) |
| `GET` | `/api/futures/{symbol}` | `get_futures_symbol(symbol, req)` | 5650 | Force-refresh Futures metrics for one symbol (bypasses cache) |
| `GET` | `/api/delta_vol` | `get_delta_vol()` | 5665 | Rolling delta volume state for all symbols (freshness indicator included) |
| `GET` | `/api/gold/status` | `get_gold_status(req)` | 5686 | Gold provider status: Twelve Data vs Yahoo fallback, API usage check |

---

## 9. Global State Stores

| Variable | Line | Type | Purpose |
|---|---|---|---|
| `candle_store` | 501 | `Dict[str, pd.DataFrame]` | Live 30s OHLCV candles per symbol (from resample_and_push) |
| `raw_1s` | 502 | `Dict[str, List[dict]]` | Raw 1s OHLCV ticks per symbol (rolling buffer, max MAX_1S=1800) |
| `signals` | 516 | `Dict[str, dict]` | Latest computed signal per symbol (score, side, confs, entry, sl, tps, etc.) |
| `h4_store`, `h2_store`, `h1_store` | 508–510 | `Dict[str, pd.DataFrame]` | Cached multi-TF DataFrames (4H, 2H, 1H) |
| `m30_store`, `m15_store`, `m5_store`, `m3_store`, `m1_store` | 511–515 | `Dict[str, pd.DataFrame]` | Cached multi-TF DataFrames (30m, 15m, 5m, 3m, 1m) |
| `d1_store` | 544 | `Dict[str, pd.DataFrame]` | Daily OHLCV per symbol for 1D macro bias |
| `futures_store` | 548 | `Dict[str, dict]` | Latest Futures metrics (OI, funding, mark price) per symbol |
| `gold_store` | 551 | `Dict[str, pd.DataFrame]` | Gold XAU/USD 4H candles (overrides PAXG H4) |
| `_delta_vol` | 558 | `Dict[str, dict]` | Rolling delta volume state per symbol (buy_vol, sell_vol, delta_pct, bullish, bearish) |
| `signal_history` | 600 | `Dict[str, List[dict]]` | Historical signal records per symbol (max 500; persistent) |
| `scoring_weights` | 601 | `Dict[str, Dict[str, float]]` | Adaptive ML weights per symbol per criterion (persistent, default 1.0) |
| `_best_results_2025` | 527 | `Dict[str, Dict]` | Best SL/TP configuration per symbol from Module 18 optimization |
| `_strict_store` | 997 | `Dict[str, dict]` | STRICT TRIX params, sharpe, next_recalib_ts per symbol |
| `_strict_heatmaps` | 1000 | `Dict[str, dict]` | Full TRIX heatmap data per symbol (served via `/api/strict/heatmap/{symbol}`) |
| `ws_clients` | 1005 | `Dict[str, Set[WebSocket]]` | Active WebSocket connections per symbol |
