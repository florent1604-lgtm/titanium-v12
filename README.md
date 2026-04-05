# Titanium v12 — Algorithmic Trading Dashboard (SMC)

> **Real-time crypto trading signal analyzer** using Smart Money Concepts (SMC) with adaptive ML, macro risk filtering, and AI vision via Ollama.

[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## Features

- **11-point SMC scoring** — EMA200, OB/FVG, BOS, TRIX, ADX, Liquidity Sweep, Delta Volume
- **Walk-forward optimizer** — bidirectional SL/TP backtesting with IS/OOS validation
- **Adaptive weights** — per-symbol signal weights updated every 50 signals
- **Cooling period** — 300s debounce per symbol/side with correlation ID tracking
- **Circuit breaker** — auto-disable on low winrate or high drawdown
- **FUNDAMENTALS module** — macro risk scoring (0–100) from NewsAPI + GDELT + RSS feeds
  - Signal cancellation above risk threshold (default: 70)
  - Proportional score reduction in mid-risk zone (30–70)
  - Auto-rollback with `ALERT_FUNDAMENTALS.md` notification
- **AI Vision** — local Ollama (LLaVA / Qwen2.5-VL) chart analysis
- **Real-time WebSocket** — per-symbol signal streaming
- **Telegram alerts** — configurable score threshold

## Architecture

```
API Gateway (FastAPI :8080)
│
├── /state          → full app state
├── /ws/{symbol}    → real-time signal stream
├── /api/optim/*    → walk-forward optimization
├── /api/chat       → Ollama vision AI
└── /fundamentals/* → macro risk score & news
       │
       ├── Signal Engine (SMC, 5s scan)
       │     └── Scoring /11 → Modulated by FUNDAMENTALS
       ├── Optimizer (SL/TP, 24h)
       ├── Strict Engine (TRIX recalib, 2d)
       ├── Learning Engine (adaptive weights)
       └── FUNDAMENTALS (news + risk, 15min)
             ├── NewsAPI
             ├── GDELT v2
             └── RSS (Reuters, BBC, CoinDesk...)
```

## Quick Start

### 1. Install dependencies

```bash
pip install fastapi uvicorn aiohttp numpy pandas pandas-ta python-dotenv
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Run

```bash
python main.py
# Dashboard → http://localhost:8080
```

## Supported Assets

| Symbol | Data Source |
|--------|-------------|
| BTC/USDT | Binance WebSocket |
| ETH/USDT | Binance WebSocket |
| SOL/USDT | Binance WebSocket |
| PAXG/USDT | Twelve Data (XAU/USD real data) |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard HTML |
| `/api/state` | GET | Full state (signals, weights, OI) |
| `/ws/{symbol}` | WS | Real-time signal stream |
| `/api/optim/results` | GET | Walk-forward optimization results |
| `/api/optim/run` | POST | Trigger manual optimization |
| `/api/delta-vol` | GET | Delta volume per symbol |
| `/api/futures/{symbol}` | GET | OI, funding rate, mark price |
| `/api/metrics` | GET | Lightweight metrics |
| `/api/chat` | POST | Ollama vision AI analysis |
| `/fundamentals/score` | GET | Macro risk score (0–100) |
| `/fundamentals/news` | GET | Latest aggregated articles |
| `/fundamentals/history` | GET | 7-day risk score history |
| `/fundamentals/reload` | POST | Force news refresh |
| `/fundamentals/enable` | POST | Enable module (runtime) |
| `/fundamentals/disable` | POST | Disable module (runtime) |

## Configuration

See [`.env.example`](.env.example) for all available options.

Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `SCAN_INTERVAL` | `5` | Seconds between signal scans |
| `SCORE_MIN_REQUIRED` | `7` | Minimum score to emit signal |
| `SIGNAL_COOLDOWN_SEC` | `300` | Cooldown between same-side signals |
| `FUNDAMENTALS_ENABLED` | `1` | Enable macro risk module |
| `FUNDAMENTALS_RISK_BLOCK` | `70` | Risk score above which signals are cancelled |
| `NEWSAPI_KEY` | _(empty)_ | NewsAPI key (free: 100 req/day at newsapi.org) |
| `GDELT_ENABLED` | `1` | GDELT v2 news (free, no key required) |

## Scoring System (11 criteria)

| # | Criterion | Timeframe | Description |
|---|-----------|-----------|-------------|
| 1 | `EMA200_H4` | 4H | Directional bias |
| 2 | `STRUCT_H2H1` | 2H/1H | Break of Structure |
| 3 | `OB_FVG_30M` | 30M | Order Block / Fair Value Gap |
| 4 | `OB_FVG_15M_CONFIRM` | 15M | Double confirmation |
| 5 | `REJET_15M` | 5M/15M | Rejection candle |
| 6 | `TRIX_5M` | 5M | TRIX/Signal cross (walk-forward optimized) |
| 7 | `ALIGN_H2H1` | 2H+1H | Bonus: H2+H1 alignment |
| 8 | `EMA200_1D` | 1D | Macro daily bias |
| 9 | `DELTA_VOL` | Live | Buy/sell pressure (notional-weighted) |
| 10 | `LIQ_SWEEP` | 30M | Liquidity sweep / stop hunt |
| 11 | `ADX_REGIME` | 30M | Trend/range filter |

## FUNDAMENTALS Module

The macro risk module filters SMC signals based on global news sentiment:

```
risk_score ∈ [0, 30]   → signal unchanged
risk_score ∈ (30, 70)  → score × (1 - ((risk-30)/40) × 0.5)
risk_score ∈ [70, 100] → signal cancelled
```

**Risk sources:**
- **NewsAPI** — 100 sources, configurable keywords
- **GDELT v2** — real-time global news index (free)
- **RSS** — Reuters, BBC, CoinDesk, CoinTelegraph

**Auto-rollback:** if the module reduces signals by >30% consistently, it auto-disables and writes `ALERT_FUNDAMENTALS.md`.

## Contributing

Issues and PRs are welcome! See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system design.

Areas for improvement:
- More sophisticated NLP (beyond keyword matching)
- Additional assets (ETH, SOL)
- Dashboard UI improvements
- Order execution integration

## License

MIT — See [LICENSE](LICENSE) for details.

> **Disclaimer:** This is an educational project. Not financial advice. Always do your own research before trading.
