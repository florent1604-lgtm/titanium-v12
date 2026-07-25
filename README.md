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
- **Paper Trading Engine** — full realistic simulation (slippage, spread, fees, funding)
  - Risk-based position sizing (% capital / SL distance)
  - Partial exits: TP1 (33%) → SL at breakeven, TP2 (33%), TP3 (34%)
  - Equity curve, max drawdown, Sharpe, winrate, expectancy — live
  - Persistent journal (JSON + CSV)
- **TradingView Webhook** — receive external alerts via `POST /webhook/tradingview`
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

### Windows PowerShell (no Docker)

```powershell
git clone https://github.com/florent1604-lgtm/titanium-v12.git
cd titanium-v12

# one-command setup + optional smoke tests + run
powershell -ExecutionPolicy Bypass -File .\tools\run_local_windows.ps1
```

Install-only mode (recommended on a machine where live bot already runs on 8090):

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_local_windows.ps1 -InstallOnly
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Run

```bash
python main.py
# Dashboard -> http://localhost:8090
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

## Paper Trading Mode

Paper Trading is enabled by default (`TRADING_MODE=paper` in `.env`). No API key required.

### How it works

Every signal emitted by the SMC engine (score ≥ threshold, cooling passed, Fundamentals OK) is automatically sent to the `PaperExecutor`, which:

1. **Validates** the signal (price > 0, SL valid, no existing position on symbol)
2. **Sizes the position** → `risk_usdt = equity × PAPER_RISK_PCT` / `sl_distance_pct`
3. **Applies slippage + spread** to the entry price
4. **Deducts entry fees** (taker rate)
5. **Monitors** the position on every 5s scan tick:
   - SL hit → full close
   - TP1 hit → close 33%, move SL to breakeven
   - TP2 hit → close another 33%
   - TP3 hit → close remaining 34%
   - Funding charged every 8h (long positions pay)
6. **Journals** every closed trade to `data/paper_journal.json` and `data/paper_journal.csv`

### Paper Trading API

| Endpoint | Description |
|----------|-------------|
| `GET /paper/state` | Full account state (equity, positions, stats) |
| `GET /paper/positions` | Open positions with live unrealized PnL |
| `GET /paper/trades?limit=50` | Closed trade history |
| `GET /paper/stats` | Winrate, Sharpe, expectancy, drawdown |
| `GET /paper/equity-curve?last_n=200` | Equity curve data points |
| `POST /paper/reset` | Reset account to initial capital |
| `POST /paper/close/{symbol}` | Manually close a position `{"price": 12345}` |

### Configuration

```env
TRADING_MODE=paper             # paper | disabled
PAPER_INITIAL_CAPITAL=1000.0   # Starting capital (USDT)
PAPER_RISK_PCT=0.02            # 2% capital risked per trade
PAPER_SLIPPAGE_BPS=5           # 0.05% slippage per execution
PAPER_SPREAD_BPS=2             # 0.02% half-spread
PAPER_FEE_BPS=4                # 0.04% taker fee (Binance standard)
PAPER_FUNDING_RATE_8H=0.01     # 0.01% funding per 8h (long pays)
PAPER_MAX_POSITIONS=3          # Max simultaneous positions
PAPER_MAX_EXPOSURE_PCT=0.60    # Max 60% of equity exposed
PAPER_TRAILING_STOP=0          # Enable trailing stop (0/1)
```

### TradingView Webhook

Send TradingView alerts to Titanium via `POST /webhook/tradingview`.

**Alert message template** (paste in TradingView alert "Message" field):
```json
{
  "secret": "your_shared_secret",
  "ticker": "{{ticker}}",
  "action": "{{strategy.order.action}}",
  "price":  {{close}},
  "score":  8,
  "strategy": "SMC_v12",
  "comment": "BOS + OB/FVG"
}
```

**Webhook URL**: `http://your-ip:8080/webhook/tradingview`

**Configuration**:
```env
WEBHOOK_ENABLED=1
WEBHOOK_SECRET=your_shared_secret   # Leave empty to disable authentication
```

The webhook:
1. Validates the secret
2. Normalizes the symbol (BTCUSDT → BTC/USDT)
3. Computes SL/TP via risk manager if not provided
4. Filters through Fundamentals if active
5. Executes via the Paper Executor
6. Returns `{"status": "accepted|rejected|filtered", "position": {...}}`

Check status: `GET /webhook/status`

---

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
