# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Environment (this machine)

- **Canonical folder: `C:\Users\flore\Desktop\v12`** — the only live copy. A former
  duplicate in `Downloads\files\titanium-v12` was merged here (07/2026) and archived;
  never work there.
- **Port: 8090** (`.env` overrides the 8080 default in `utils/config.py`). Port 8080 is
  taken by JARVIS's mobile server — do not move Titanium back to 8080.
- **Python: use the project venv** — `venv\Scripts\python.exe` (all deps installed there).
- **JARVIS integration**: `C:\Program Files\JARVIS\titanium_connector.py` polls this API on
  port 8090 every 10s (`/api/state`, `/paper/stats`, `/paper/positions`, `/fundamentals/score`).
  Renaming/moving those endpoints breaks JARVIS voice commands.
- The bot often runs 24/7. **Edits to API/engine code require a restart of `main.py`**
  to take effect — say so explicitly after changing server code.

---

## Quick Start & Essential Commands

### Launch Titanium
```bash
cd C:\Users\flore\Desktop\v12
venv\Scripts\python.exe main.py
# Dashboard: http://localhost:8090   (v13 one-screen: http://localhost:8090/v13)
# API docs: http://localhost:8090/docs
```

### Run Tests
```bash
venv\Scripts\python.exe -m pytest tests/ -v                      # All tests
venv\Scripts\python.exe -m pytest tests/test_paper_trading.py -v # Paper trading only
venv\Scripts\python.exe -m pytest tests/test_modulator.py -v     # Fundamentals only
venv\Scripts\python.exe -c "from api.api_server import app; print('OK')"  # Sanity check
```

### Verify Configuration
```bash
python -c "from utils.config import SYMBOLS, SCAN_INTERVAL; print(f'Symbols: {SYMBOLS}, Interval: {SCAN_INTERVAL}s')"
```

### Key Files (don't miss)
| File | Purpose |
|------|---------|
| `.env` | All config variables (Binance keys, FUNDAMENTALS settings, port 8090, etc.) |
| `main.py` | Entry point — spawns 9+ async loops |
| `utils/config.py` | Single source of truth for all env vars (never call `os.getenv()` directly) |
| `core/signal_engine.py` | 5s scan loop — orchestrates scoring, modulation, signal emission |
| `docs/ARCHITECTURE.md` | Full data flow diagram + module breakdown |

---

## Architecture at a Glance

### Data Flow (per-symbol)
```
Binance WS (aggTrade)
    ↓
candle_store[sym] (1s → 30s bars)
    ↓
score_setup() (11 criteria) → score ∈ [0, 11]
    ↓
get_macro_risk() (FUNDAMENTALS) → risk ∈ [0, 100]
    ↓
modulate() (scale score by risk factor)
    ↓
emit_signal() (cooling 300s per sym/side)
    ↓
broadcast() [WebSocket] + send_signal_alert() [Telegram]
```

### Module Breakdown

| Module | Path | Role | Criticality |
|--------|------|------|-------------|
| **Signal Engine** | `core/signal_engine.py` | Async scan loop (5s), runs `score_setup()` + `modulate()` per symbol | **CRITICAL** |
| **Scoring /11** | `core/scoring_engine.py` | SMC criteria (EMA200, OB/FVG, BOS, RSI, ADX, TRIX, delta vol, liquidity) | **CRITICAL** |
| **SMC Engine** | `core/smc_engine.py` | Detects order blocks, fair value gaps, break of structure, sweeps | Core scoring |
| **FUNDAMENTALS** | `fundamentals/` | Macro risk scoring (news + sentiment) — filters/scales signals | High |
| **Paper Trading** | `execution/paper_trading.py` | Full realistic backtest (slippage, fees, funding, drawdown tracking) | High |
| **Optimizer** | `engine/optimizer.py` | Walk-forward SL/TP tuning (24h loop) | Maintenance |
| **Spectral** | `indicators/spectral.py` | Cycle detection — two APIs: `compute_spectral_features` (scipy → scoring) + `analyze` (causal Ehlers → dashboard) | Research |
| **Order Book L2** | `data/orderbook_ws.py` + `indicators/orderbook.py` | Depth streams, imbalance/wall analysis fed into `score_setup()` (`ORDERBOOK_L2_ENABLED`) | High |
| **JARVIS alerts** | `assistant/signal_alert.py` | Voice alerts on score ≥ threshold (started in lifespan) | Medium |
| **Event bus** | `utils/event_bus.py` | Typed events (`data/events.jsonl`) — passive | Low |
| **Guards** | `execution/guards.py` | Pre-execution guard pipeline (correlated exposure, blackout) — default off | Medium |
| **Services panel** | `api/services_routes.py` | Dashboard start/stop for Titan/Ollama/GitNexus + `/services/github/push` (git add/commit/push from the dashboard) | Medium |

### Active Async Loops (lifespan in `api/api_server.py`)
| Loop | Interval | Purpose |
|------|----------|---------|
| `ws_binance` (×N) | Continuous | Feed 1s candles per symbol |
| `scan_loop` | 5s | Core scoring + signal emission |
| `fundamentals_loop` | 900s (15 min) | Refresh macro risk score |
| `optimization_loop` | 24h | Walk-forward SL/TP recalibration |
| `strict_recalib_loop` | 2d | TRIX parameter recalibration |
| `learning_report_loop` | 2h | Adaptive weights update + circuit breaker check |
| `circuit_breaker_loop` | 1h | Monitor winrate / drawdown thresholds |
| `gold_refresh_loop` | Varies | PAXG/XAU data (Twelve Data + Yahoo fallback) |
| `futures_refresh_loop` | 60s | Open interest, funding rate, mark price |
| `external_feeds_loop` | Varies | Extra fundamentals feeds (`fundamentals/external_feeds.py`) |
| Orderbook L2 streams | Continuous | Started via `start_orderbook_streams()` before the loops |

Startup also runs `_seed_candle_store(session)` (REST 1m → resampled 30s bars) so the
scan is operational in seconds instead of waiting ~5 min for WS accumulation.

---

## Key Concepts

### Scoring System (/11 criteria)
Each symbol is scanned every 5s against 11 SMC-based criteria. Each criterion returns 0 or 1 point; sum is the base score.
Signals emit when `score ≥ SCORE_MIN_REQUIRED` (default: 7).

**The 11 Criteria:**
1. EMA 200 (4H) — directional bias
2. Break of Structure (2H/1H alignment)
3. Order Block or Fair Value Gap (30M)
4. OB/FVG double confirmation (15M)
5. Rejection candle (5M/15M)
6. TRIX/Signal cross (5M, walk-forward optimized)
7. Bonus: H2+H1 alignment
8. EMA 200 (1D macro bias)
9. Delta volume (buy/sell pressure, notional-weighted)
10. Liquidity sweep detection (30M)
11. ADX trend/range filter (30M)

### Fundamentals Module (Macro Risk Filter)
**Risk Score (0–100)** calculated every 15 min from NewsAPI + GDELT + RSS.
- **0–30**: Signal unchanged
- **30–70**: Score × (1 - ((risk-30)/40) × 0.5)  [proportional reduction]
- **70–100**: Signal cancelled

Config: `FUNDAMENTALS_ENABLED`, `FUNDAMENTALS_RISK_BLOCK`, `FUNDAMENTALS_RISK_REDUCE`.
Endpoint: `/fundamentals/score` returns current score + risk level + modulation stats.

### Paper Trading
Simulates real fills with:
- Slippage: `PAPER_SLIPPAGE_BPS` (5 bps default)
- Spread: `PAPER_SPREAD_BPS` (2 bps)
- Fees: `PAPER_FEE_BPS` (4 bps taker)
- Funding costs (futures)

Position sizing: `% capital / ATR-based SL distance`. Exits: TP1 (33% → SL at breakeven), TP2 (33%), TP3 (34%).

### Spectral Analysis (Phase 1 wired, regime filter off by default)
Module `indicators/spectral.py` exposes **two complementary APIs** (kept from the 07/2026
merge — do not delete either):
- **`compute_spectral_features(close) → SpectralFeatures`** (scipy, non-causal filtfilt/hilbert).
  Consumed by `core/signal_engine.py`: results stored in `spectral_state[sym]` and passed to
  `score_setup(spectral_features=...)`. Gated by `SPECTRAL_REGIME_FILTER` (default **off** —
  it must stay off until walk-forward validated).
- **`analyze(close_series) → dict`** (pure numpy, 100% causal, Ehlers-style). Used only for
  dashboard instrumentation (`ctx["spectral"]`), safe for live.

Outputs: dominant cycle (bars), cycle power (0–1), phase (0–360°), phase zone.
**Causal warning**: `compute_spectral_features` uses lookahead — backtest/visualisation only;
`analyze` is the causal path.

---

## Configuration & Data Persistence

### Environment Variables (`.env`)
Centralized in `utils/config.py`. Key groups:
- **Binance**: `BINANCE_KEY`, `BINANCE_SECRET`, `BINANCE_SYMBOLS`
- **Data**: `ACTIVE_TF`, `SCAN_INTERVAL`, `CACHE_TTL` per timeframe
- **Scoring**: `SCORE_MIN_REQUIRED`, `SCORE_CRITERIA` (weights)
- **FUNDAMENTALS**: `FUNDAMENTALS_ENABLED`, `FUNDAMENTALS_RISK_BLOCK`, `NEWSAPI_KEY`
- **Paper Trading**: `PAPER_INITIAL_CAPITAL`, `PAPER_FEE_BPS`, circuit breaker thresholds
- **Spectral**: `SPECTRAL_ENABLED`, `SPECTRAL_TF`, `SPECTRAL_PMIN/PMAX`, `SPECTRAL_POWER_THRESHOLD`
- **Ollama/Titan**: `TITAN_ENABLED`, `TITAN_LLM_MODEL`, `OLLAMA_BASE_URL`

### Persistent State Files
- `data/paper_state.json` — Account equity, positions, P&L
- `data/paper_journal.json/csv` — Trade ledger
- `data/signal_history.json` — Used by learning engine for adaptive weights
- `param_registry.json` — Cached parameters (SL/TP ranges per symbol)
- `scoring_weights.json` — Adaptive weights per criterion/symbol

All files are reloaded on startup; changes during runtime are saved atomically.

---

## Code Patterns & Guidelines

### Adding a New Scoring Criterion
1. **Implement the detector** in `core/smc_engine.py` or `indicators/`.
2. **Add to `score_setup()`** in `core/scoring_engine.py`: call detector, return 0/1.
3. **Add to config** in `utils/config.py`: default weight + override per symbol.
4. **Document** in README.md (scoring table) + docs/ARCHITECTURE.md.
5. **Test** with `pytest tests/test_scoring.py` (if exists) or manual backtest.
6. **Do NOT increment the /11 count** until walk-forward validated.

### Modifying Signal Emission / Cooling Logic
**Before editing `execution/signal_manager.py`**:
1. Run `gitnexus_impact({target: "emit_signal", direction: "upstream"})`.
2. Note: `emit_signal()` is called per symbol in `signal_engine.py` (5s loop) — changes affect real-time behavior.
3. Cooling period (300s) is enforced per `(symbol, side)` pair with `correlation_id` tracking; don't remove without understanding cooldown intent.
4. Test thoroughly: `python -m pytest tests/ -v` + manual backtest.

### Editing FUNDAMENTALS Module
The macro risk filter affects **all signals**. Before changing:
1. **`modulate()`** in `fundamentals/signal_modulator.py` — scales score by risk factor.
2. **`get_current_score()`** in `fundamentals/risk_scorer.py` — computes 0–100 risk from news.
3. Always ensure `score_after_modulation` is clamped to [0, 11].
4. Test with `pytest tests/test_modulator.py tests/test_risk_scorer.py -v`.

### Paper Trading Tuning
- **SL/TP levels** computed in `execution/risk_manager.py` based on ATR + symbol overrides.
- **Position sizing** in `execution/executor.py` — `(capital × risk%) / SL_distance`.
- **Fills** simulated in `execution/paper_trading.py` — slippage + spread applied.
- Backtest results saved to `data/paper_journal.json` — always verify cumulative P&L matches.

---

## GitNexus Integration (Code Intelligence)

This project is indexed by GitNexus (4500+ symbols, 7000+ relationships).

> **Availability note**: the GitNexus MCP tools and `.claude/skills/gitnexus/` skill files
> are not installed in every session. If `gitnexus_*` tools are unavailable, skip this
> section entirely and use standard tools (Grep/Read) — do not block on it.

### Before Editing Any Symbol
```bash
gitnexus_impact({target: "symbolName", direction: "upstream"})
```
Returns: direct callers, affected processes, risk level (LOW/MEDIUM/HIGH/CRITICAL).

### Workflow
1. **Explore**: `gitnexus_query({query: "how does scoring work?"})`  
   → Returns ranked execution flows grouped by process.
2. **Understand**: `gitnexus_context({name: "score_setup"})`  
   → Full caller graph + execution flows.
3. **Edit**: Run impact analysis first. Edit the symbol.
4. **Verify**: `gitnexus_detect_changes()` before committing.
5. **Update Index**: `npx gitnexus analyze` after commit.

### Key GitNexus Queries
- `"what happens when a signal is emitted?"` → traces emit → broadcast → WebSocket
- `"how is macro risk computed?"` → traces news fetch → risk scoring → modulation
- `"which tests validate paper trading?"` → returns test file + coverage map

**Never rename symbols with find-and-replace** — use `gitnexus_rename` (understands call graph).

---

## Testing & Validation

### Test Coverage
- **`tests/test_paper_trading.py`** — Entry/exit fills, partial exits, drawdown.
- **`tests/test_modulator.py`** — Risk reduction thresholds, edge cases.
- **`tests/test_risk_scorer.py`** — News parsing, risk EMA, velocity calculation.
- **`tests/test_orderbook_l2.py`** — L2 imbalance/wall analysis.
- **`tests/test_spectral_scoring.py`** — Spectral features → scoring integration.
- **`tests/test_guards.py`** / **`test_trade_journal.py`** / **`test_signal_alert.py`** — Guards, journal, JARVIS alerts.
- **`tests/test_mcp_server.py`** / **`test_antigravity_cli_bridge.py`** — MCP/bridge integrations.

### Backtests
- `scripts/backtest_cli.py` — CLI backtest runner.
- `tools/backtest_ab_6m.py` — A/B 6-month backtest (validated the time-stop:
  `PAPER_MAX_HOLD_HOURS` is the canonical variable; `PAPER_MAX_AGE_HOURS` is a legacy
  duplicate still present in config).

### Before Committing
```bash
python -m pytest tests/ -v
python -c "from api.api_server import app; print(f'{len(app.routes)} routes')"
git status  # Review changes
gitnexus_detect_changes()
```

### Walk-Forward Validation (for new scoring criteria)
1. Backtest on 3-month historical data (IS phase).
2. Validate on 1-month out-of-sample (OOS phase).
3. Winrate must be ≥ 55% and Sharpe > 1 before shipping.
4. Log results in `docs/` for future reference.

---

## Common Workflows

### "Signals are low-quality — what's wrong?"
1. Check circuit breaker status: `curl http://localhost:8090/paper/stats`
2. Verify scoring weights: `cat scoring_weights.json`
3. Check fundamentals risk: `curl http://localhost:8090/fundamentals/score`
4. Run backtest: `python -m pytest tests/test_paper_trading.py -v`
5. Review signal_history.json for pattern (learning engine may have de-weighted criteria).

### "I want to enable a new feature (e.g., Spectral Phase in scoring)"
1. **Phase 0** ✅ — Spectral already logs cycle + phase (read-only).
2. **Phase 1** → Integrate into `/11` scoring:
   - Add `phase_zone` to `score_setup()`.
   - Validate walk-forward (70/30 split, Sharpe > 1).
   - Update `docs/ARCHITECTURE.md` + scoring table.

### "Paper trading P&L doesn't match manual calculation"
1. Extract journal: `cat data/paper_journal.json | python -m json.tool`
2. Verify fees: entry_fee = quantity × price × fee_bps / 10000.
3. Verify slippage: check `PAPER_SLIPPAGE_BPS` + `PAPER_SPREAD_BPS`.
4. Check funding: futures positions include funding costs.
5. Inspect `execution/paper_trading.py` → `_apply_fill()` for exact formula.

---

## Resources & Documentation

| Resource | Contents |
|----------|----------|
| `README.md` | Overview, features, quick start, API endpoints |
| `docs/ARCHITECTURE.md` | Full data flow, module table, async loops |
| `docs/COMMANDES.txt` | All CLI commands, troubleshooting, setup guide |
| `docs/TITANIUM_V12_SPECTRAL_ROADMAP.md` | Spectral research (Ehlers, phase calibration, Phase 2/3 planning) |
| `docs/` | Audits (SMC, perf, signal flow), roadmaps, walk-forward validation logs |
| `ALERT_FUNDAMENTALS.md` | Risk event log (rollback timestamps, score spikes) |

---

## Debugging Checklist

- **No signals after 5 minutes**: Normal — waiting for MIN_DF30_FOR_SCAN bars to accumulate. Check logs: `[SCAN] {sym} — df30 insufficient (X bars, min=10)`.
- **Circuit breaker active**: Run `curl -X POST http://localhost:8090/paper/reset-circuit-breaker`.
- **Dashboard GitHub push fails**: the route is `POST /services/github/push`
  (`api/services_routes.py`). Historical bug: an untyped `request` param caused a
  systematic 422 — the param must stay `request: Request`. A running bot serves the
  code it was started with; restart after editing routes.
- **WebSocket not broadcasting**: Check lifespan in `api/api_server.py` — is `_broadcast_fn` set?
- **Fundamentals stuck at risk=100**: Restart news loop or POST `/fundamentals/reload`.
- **Paper trading fills look wrong**: Verify `PAPER_SLIPPAGE_BPS`, `PAPER_SPREAD_BPS`, `PAPER_FEE_BPS` in `.env`.

---

## Notes for Future Work

1. **Spectral Phase → Scoring** (Phase 1): Walk-forward validate before adding to /11.
2. **Multi-timeframe spectral** (Phase 3): Correlation matrix across BTC/ETH/SOL × frequency.
3. **Macro regime detection**: Use ADX + spectral to auto-switch scoring weights.
4. **Ollama integration**: LLaVA chart analysis + intent routing via JARVIS (Titan agent).
