# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## À LIRE EN PREMIER — état courant

**`collab/ETAT_ACTUEL.md`** = briefing compact de reprise (projet, garde-fous,
équipe, état des chantiers, décisions). Le lire d'abord évite de trawler
`collab/LOG.md` (long). Puis lire le tail du bus : `node tools/collab_bus.mjs tail`.

Segments récents (07/2026) non détaillés plus bas mais actifs :
- `emotion/` — segment ÉMOTION (circumplex valence×arousal ; read-only, M2 avant décision).
- `domain/agent_registry.py` + `orchestrator.py` + `voice_intents.py` + `llm_planner.py` — Patron A (orchestration LLM fail-closed, câblé JARVIS).
- `execution/demo_mt5_executor.py` + `demo_bridge.py` — exécution DÉMO MT5 (étape D, fail-closed, mur démo↔réel).
- `mcp_gitnexus_gate.py` + `tools/gitnexus_write_policy.py` — garde d'écriture GitNexus signé Ed25519 (clés provisionnées ; writes bloqués tant que detect_changes crash).

---

## Pyramid Architecture (N0→N6) — CURRENT canonical structure (reorg, 07/2026)

> **Read this before trusting file paths elsewhere in this doc.** A structural "pyramid"
> reorg (branch **`reorg/phase1`**, `master` frozen at `aefded3`) physically moved most
> engines into level-named packages. **The old paths still import** because each old
> location is now a 4-line **`sys.modules` shim** that re-exports the real module — so
> `core/signal_engine.py`, `core/confluence_demo_engine.py`, `data/mt5_provider.py` etc.
> **still work**, but the code lives elsewhere now. Resume file: **`REORG_STATE.md`**
> (always read first); cartography: `TITANIUM_V12_INDEX.md` + `REORG_AUDIT.md`.

**Control flows UP the pyramid; data flows both ways through the N0 socle** (a shared
`SystemState` + append-only journal that every level reads/writes).

| Level | Package (real code) | What lives there | Old shim path |
|---|---|---|---|
| **N0 socle** | `core/state.py`, `core/journal.py`, `core/config.py`, `core/flux.py`, `core/state_builder.py`, `core/health.py`, `core/cloe/` | `SystemState` (Pydantic v2 blocks), SQLite append-only journal (signal/decision/fill/ghost), pydantic-settings, continuous afferent flux store, state builder + rich rationale, `/health`, Cloe memory+confidence | — (new) |
| **N1 ingestion** | `ingestion/market/` | `binance_ws`, `mt5_provider` (⚠️ `mt5_lock`), `orderbook_ws`, `futures_data`, `gold_provider`, `spread_tracker` | `data/*` |
| **N2 pôles** | `poles/smc/`, `poles/spectral/`, `poles/fundamentals/`, `poles/emotion/`, `poles/vision/` | scoring/smc/signal engines; geometric_plane+spectral; risk_scorer+modulator; emotion; vision | `core/*`, `indicators/spectral`, `fundamentals/*`, `emotion/*`, `vision/*` |
| **N3 fusion** | `fusion/` | `confluence_demo_engine` (`run_once`/`decide`), `confluence_adapter`, `consensus_engine`, `cortex`, `lead_lag_engine` | `core/*` |
| **N4 porte** | `risk/riskgate.py` | **single decision gate** `RiskGate.evaluate(SystemState)→Decision(ALLOW/REDUCE/DENY)` | — (new; consolidates guards/risk_manager/portfolio_risk/brain_gate/circuit-breaker/trend filter) |
| **N5 exécution** | `execution/` | `executor` (paper), `paper_trading` (sim), `demo_mt5_executor`+`demo_bridge` (MT5 démo), `demo_position_manager` | (unchanged) |
| **N6 feedback** | `feedback/` | `optimizer`, `learning_engine`, `strict_engine` (+ `tools/trade_analytics`, `trade_postmortem`) | `engine/*` |

`brain_gate.py` intentionally stays in `core/` (not moved). **Shim cleanup is deferred to
the very end** — do not delete shims while old import paths remain in the tree.

### N4 RiskGate — WIRED as an additive, reversible veto (`RISKGATE_ENABLED=1`)
`fusion/confluence_demo_engine.py::run_once` calls `RiskGate().evaluate(state)` on demo
placements. Order inside the gate: HALT → fundamentals veto → circuit breaker → pre-entry
→ trend filter (reversal-aware) → **cost is INFORMATIVE only** → **sizing = Cloe confidence**.
It is **fail-OPEN** (a RiskGate bug never blocks a trade) and only acts when the heart already
allows and `source != MASTER`. `RISKGATE_PILLAR_LADDER` is flat (`1:1.0…5:1.0`): the old
"more pillars = bigger lot" factor was replaced by the confidence index.

### Sizing model — lot ∝ RISK × Cloe confidence (Florent's rule; cost is NOT in the formula)
`core/cloe/confidence.py::confidence_for(symbol, side, n_pillars, regime) → [0.2, 1.0]` reads
**measured net-of-cost expectancy per context** from `data/trade_analytics.json` (category /
side / structure / symbol), shrinks toward 0.5 on thin samples, and threads into placement as
`size_factor` (`riskgate_conf`). Cost enters **indirectly** (a context where cost kills the
edge shows negative measured perf → low confidence → small lot). Neutral 0.5 when no data.
**Current reality:** all contexts measure < 0.5 (strategy net-negative) → small lots everywhere,
which is the intended prudent behaviour while the learning loop accumulates data.

### Cost-aware findings baked into the code (don't re-litigate without new backtests)
`tools/backtest_riskgate.py` (real Axi spreads, per-symbol) replays the same decision path.
Conclusions: **cost is the dominant killer** (baseline PF ≈ 0.20 matches live); adapting lot
to context helps but the raw edge is marginal; **wider targets do NOT rescue it** (TP sweep →
`CONFLUENCE_DEMO_TP_ATR=2.25` / R:R 1.5 is the measured optimum, wider degrades). The remaining
real lever is **selectivity** (trade only proven-profitable contexts) — deferred until the
confidence loop has enough data. Run: `venv\Scripts\python.exe -m tools.backtest_riskgate`.

---

## Cloe — the local AI layer (07/2026). Read before touching anything LLM-related.

Florent's framing (28/07, and it corrects the natural instinct to treat Cloe as a bolt-on
risk): **Cloe is not an add-on, she is the logical continuation of the engines.** The bot's
structured perceptions must *nourish* her so she reaches the deterministic core's level and
then exceeds it. His goal is explicitly **not** immediate trading profit — it is to grow the
system. Priority is therefore **nourishment first, gating second**.

### Hardware reality — this dictates every design choice
CPU-only (Ryzen 7 7730U, **no GPU usable by Ollama**), **15.4 GB RAM / ~7.5 GB free**.
A 7B model ≈ 4 tok/s; `phi3:medium` (8 GB) alone would swap the machine and starve the bot.

### Two-speed Cloe (the architecture)
| | 🔵 **Réflexe** (in/near the loop) | 🟣 **Exploratrice** (background) |
|---|---|---|
| Model | small, **resident** (`qwen2.5:3b`) | big models, on demand |
| Tools | ❌ **none** — no browser, no MCP, no network | ✅ browser, MCP, advisor models |
| Latency | **1.3 s warm** (measured), hard timeout, **fail-open** | unbounded, irrelevant |
| Role | **reads** memory (µs) | **writes** memory |

**The mechanism that makes it work:** the Réflexe never "thinks" at decision time — it reads
what the Exploratrice already concluded. Intelligence grows in the background; decisions stay
instant. This pattern is already proven in the codebase (`confidence_for()` reads
`trade_analytics.json` instantly while analytics compute in background) — Cloe extends it.

**Escalation (validated, not yet built):** a deterministic **doubt score** (confidence in the
0.45–0.55 grey zone, `BRAIN_SIDE_CONFLICT`, `topology_alert`, unseen context n<5, macro↔technical
contradiction) triggers escalation. Never an LLM deciding whether to call an LLM. Key efficiency
rule: **confront context *classes*, not instances** — one verdict on "crypto/short/2 pillars/
GRASSMANN" covers the hundreds of decisions sharing that signature.

### Ollama is bridled — do NOT unset these (user-scope env vars, need an Ollama restart)
```
OLLAMA_KEEP_ALIVE=-1        # Cloe stays resident → no cold start ("consciente")
OLLAMA_MAX_LOADED_MODELS=1  # protects RAM: only one model in memory at a time
OLLAMA_NUM_PARALLEL=1       # protects CPU: never two inferences competing with the bot
OLLAMA_MAX_QUEUE=8
```
Call the reflex with `options={"num_thread": 5}` (of 16) so the trading engine keeps its cores.
Before this bridling a fusion query **timed out past 9 minutes**; after, it answers in **1.3 s**.

### Open WebUI (`http://localhost:3000`, separate venv `C:\Users\flore\open-webui`)
- **Embeddings**: `nomic-embed-text` via Ollama (`RAG_EMBEDDING_ENGINE=ollama`). Without an
  embedding model, knowledge ingestion fails silently with "content is empty".
- **Model family**: `cloe` (qwen2.5:7b), `cloe-vision` (qwen2.5vl:7b), `cloe-deep` (phi3:medium),
  `cloe-fast` (phi3:mini), plus **`cloe_super`** — a pipe function that queries several brains in
  parallel and synthesises one answer (**slow: 3 inferences; analysis only, never in the loop**).
- **Known API quirks of this version**: `POST /api/v1/models/model/update` **500s on anything**
  (even a no-op) and model deletion by query-param fails → to change a model, delete it in the UI
  and recreate via `/api/v1/models/create` (which *does* accept `meta.knowledge`). File upload is
  **asynchronous**: poll `data.content` until non-empty before `/knowledge/{id}/file/add`, else it
  400s "content is empty". Files are deduped by hash — a failed empty upload poisons later retries.
- Tools: `tools/openwebui_ingest_cloe.py` (RAG ingest, idempotent), `tools/openwebui_cloe_super.py`.

### Cloe's memory
`core/cloe/memory.py` (hierarchical, `data/cloe/memory.json`) + `core/cloe/confidence.py`
(the sizing index) + `data/cloe/knowledge/*.md` (regenerated every 10 min, ingested into RAG).

---

## The eyes of Cloe — excursion tracker (MAE/MFE), 28/07

**Why it exists:** Cloe received *sensation* (11k journaled decisions) and *statistics*
(aggregates) but never **consequence** — she knew "I decided X", never "and by how much I was
wrong". Without consequence there is no learning. This is the prerequisite to any adaptive
SL/TP work, and L2/price history is **not recoverable retroactively** — every night without
recording is lost forever.

`feedback/excursion_tracker.py` writes one immutable line per **closed** position:
- `mae_R` / `mfe_R` — how far it hurt / how far it could have gone (R fixed at entry, never recomputed)
- `giveback_R` — what was **returned after the peak** (only counted if there *was* a gain, else it
  double-counts MAE — a real defect caught by a test)
- `time_to_mfe_sec/bars`, `pnl_R`, `exit_reason`
- **`censored`** — SL/timeout/manual exit ⇒ MFE is **truncated**. Without this flag every future
  MFE estimate is biased low, permanently. Expect a high censoring rate (winrate ≈ 19 %) → a
  survival model will be required, not a naive quantile.
- `context` — the **entry perception of every organ** joined from the journal by ticket (pillars,
  `regime_geo`, `lyapunov`, **emotion**, fundamentals, macro, `roundtrip_cost`).

**Wiring (zero added latency):** grafted onto `execution/demo_position_manager.manage_once()`,
which already polls every 15 s. Its **ticket purge is the closure instant** — the only moment
where entry context *and* outcome are both still known. Exact extremes are re-read from **M1 bars**
at closure (15 s polling misses wicks); honest fallback to polling recorded in `excursion_source`.
Anchored on the broker's real open time (`ts_open`), not first observation.
Fail-safe throughout: MT5 down ⇒ degraded line, **never an exception toward trading**.
Output: `data/excursions/excursions-YYYY-MM.ndjson` (append-only, monthly rotation).

---

## Environment (this machine)

- **Canonical folder: `C:\Users\flore\Desktop\v12`** — the only live copy. A former
  duplicate in `Downloads\files\titanium-v12` was merged here (07/2026) and archived;
  never work there.
- **Port: 8090** (`.env` overrides the 8080 default in `utils/config.py`). Port 8080 is
  taken by JARVIS's mobile server — do not move Titanium back to 8080.
- **Python: use the project venv** — `venv\Scripts\python.exe` (all deps installed there).
- **JARVIS integration**: separate voice app in `C:\Program Files\JARVIS` (`main2.py`, WS
  8765, mobile 8080, own venv, launched by `DEMARRER_JARVIS.bat`). Its
  `titanium_connector.py` polls this API on port 8090 (`/api/state`, `/paper/stats`,
  `/paper/positions`, `/fundamentals/score`, `/swing/status`, `/opportunities/status`) —
  renaming/moving those endpoints breaks JARVIS voice commands. JARVIS brain (R6, 07/2026):
  **Hermes Agent priority 0** (`demander_hermes` in `main2.py`, one-shot `hermes -z … --cli`
  via `asyncio.to_thread(subprocess.run)`) with automatic fallback Claude → Gemini → local
  Ollama `qwen2.5:7b` ("mode privé"). ⚠️ Codex audit flagged CRITICAL: `hermes -z` bypasses
  approvals while loading tools — R6b hardening (tool-less profile for the voice path)
  pending Florent's arbitration; Gemini stays as safety net until parity + cutover decision. It
  ingests the living knowledge pack (see JARVIS knowledge module). **Machine is CPU-only
  (Ryzen 7 7730U iGPU, unsupported by Ollama) + 15 GB RAM** → local LLM ≈ 4 tok/s, so
  local is fallback-only, never the default voice brain.
- **JARVIS console is cp1252 too**: a `print()` with a unicode char (✔) once crashed its
  voice thread silently (WS server stayed up, so JARVIS looked "alive" but was deaf). Fixed
  by `sys.stdout/stderr.reconfigure(encoding="utf-8", errors="replace")` at the top of
  `main2.py` + `chcp 65001` in `DEMARRER_JARVIS.bat`. Symptom to remember: JARVIS window
  shows no data / high latency / no response = check the voice thread didn't die on a print.
- **JARVIS window must load `http://localhost:8090`** (set by `FRONTEND_URL` in `main2.py`),
  NOT its own static `dist/` server on 5173 — the dashboard uses relative `/paper/stats`
  + `ws://…/ws/realtime`, so serving it from anywhere but 8090 gives "reconnexion" / no data.
- **Anti-larsen guard** in JARVIS `ecouter()`: while `is_speaking`, all recognized speech is
  ignored except stop-words — otherwise the mic hears JARVIS's own TTS and it "talks to
  itself" in a loop. Don't remove the `if is_speaking: continue`.
- The bot often runs 24/7. **Edits to API/engine code require a restart of `main.py`**
  to take effect — say so explicitly after changing server code.
- **Dashboard**: single source of truth `titanium_unified.html`, deployed to BOTH
  `titanium_v12_dashboard.html` (served on 8090) and `C:\Program Files\JARVIS\frontend\dist\index.html`.
  HTML is re-read per request → **no restart needed for HTML/JS/CSS edits** (only for API code).
  It carries a self-contained contextual-help layer (hover tooltips + "?" help-mode button)
  driven by a `data-help`/glossary engine at the end of the file — extend the glossary there
  to explain new instruments/indicators.
- **Cockpit "orbe"** (DASH refonte 07/2026, `titanium_orbe.html` → route `GET /orbe`):
  JARVIS-style HUD (Iron Man `#00e5ff`, Courier New, boot/scanlines/typed subtitles) with a
  particle orb ported from `C:\Program Files\JARVIS\frontend\src\orb.ts` (canvas 2D, **zero CDN**).
  The orb has a **NEURAL NETWORK mode** showing the bot's REAL call graph — nodes/edges come from
  `GET /orbe/map`, generated by `tools/gen_neural_map.py` (prefers the GitNexus registry at
  `localhost:4747/api/graph` → Function/Method/Class/Route + CALLS edges; **falls back to AST**
  imports offline). Live activity (delta of `scan_count`/`total_trades`/`equity` between polls)
  lights up the corresponding modules. Route `GET /swing/risk/exposure` (read-only,
  `core.portfolio_risk.exposure_snapshot`) feeds the R3 risk ring. The orb is Florent's product
  decision — do NOT replace `/orbe` with another surface; new tools get their own route.
  Design brief co-signed with Codex/Hermes: `collab/DASH_DESIGN.md`. Page + map are re-read per
  request (hot iterate, no restart); regenerate the map after refactors:
  `venv\Scripts\python.exe tools\gen_neural_map.py`.
- **MCP servers**: `.mcp.json` registers `base44` (`mcp_base44.py`) and `titanium`
  (`mcp_server.py`), both stdio. Correct entrypoint pattern is
  `async with stdio_server() as (read, write): await app.run(...)` — passing the app
  to `stdio_server()` is a silent breakage (fixed 07/2026, don't reintroduce).
- **Console encoding is cp1252**: scripts printing unicode (─, ↔, é) crash unless run
  with `PYTHONIOENCODING=utf-8`.
- **`requirements.txt` drift (fixed 07-25)**: `mcp` and `MetaTrader5` ran in the venv but were
  **undeclared** → a clean `pip install -r requirements.txt` (e.g. `tools/run_local_windows.ps1`
  bootstrapping a fresh copy) produced a bot with missing deps *or* placeholder `.env` keys (the
  `.env.example` copy → `TWELVEDATA_API_KEY=your…` → **401 loops**). Both now declared; and never
  auto-run `main.py` on a copy whose `.env` was just seeded from `.env.example`.
- **Centre de Contrôle** (`centre_controle.py`, launch `pythonw centre_controle.py`): pywebview
  desktop panel — live service status + one-click surfaces + launch/restart bot. Any subprocess it
  polls (e.g. `tasklist`) MUST pass `creationflags=CREATE_NO_WINDOW`, else it flashes a black
  console every 5 s under `pythonw` (the status probe runs on a timer).

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

### Restart the running bot (⚠️ venv-shim: there are TWO `main.py` processes, ONE bot)
`venv\Scripts\python.exe` is a **relay launcher**: it spawns the real interpreter
(`…\Python312\python.exe main.py`) which owns port 8090. Killing only the listener leaves a
zombie parent. Always kill the **parent tree**, then relaunch through the venv (PowerShell):
```powershell
$c = Get-NetTCPConnection -LocalPort 8090 -State Listen | Select-Object -First 1
$p = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $c.OwningProcess)
taskkill /PID $p.ParentProcessId /T /F          # parent = venv launcher
Start-Process -FilePath "C:\Users\flore\Desktop\v12\venv\Scripts\python.exe" `
  -ArgumentList "main.py" -WorkingDirectory "C:\Users\flore\Desktop\v12" -WindowStyle Hidden
```
`reload=False`, so **any API/engine edit needs this restart**. After restart `/health` shows
`degraded` + `symbols_tracked: 0` for ~1 min — that is the first confluence cycle warming up,
not a failure. Open positions keep their broker SL/TP while the bot is down (no trailing).

### Verify Configuration & health
```bash
python -c "from utils.config import SYMBOLS, SCAN_INTERVAL; print(f'Symbols: {SYMBOLS}, Interval: {SCAN_INTERVAL}s')"
curl -s http://localhost:8090/health            # pyramid health: socle/fusion/risk/execution
curl -s http://localhost:8090/confluence/demo/status   # watchlist, crypto_enabled, heartbeat
curl -s http://localhost:11434/api/ps           # which model is RESIDENT (Cloe must stay loaded)
```

### Key Files (don't miss)
| File | Purpose |
|------|---------|
| `REORG_STATE.md` | **Read first** — pyramid reorg resume point, branch, what's wired/pending |
| `.env` | All config variables (Binance keys, FUNDAMENTALS settings, port 8090, etc.) |
| `main.py` | Entry point — spawns 9+ async loops |
| `utils/config.py` | Legacy single source of truth for env vars (94 importers). `core/config.py` (pydantic-settings) is the additive N0 successor — never call `os.getenv()` directly |
| `core/state.py` / `core/journal.py` | N0 socle: `SystemState` + append-only decision journal (uncensored: signal/decision/fill/ghost) — the shared spine every level reads/writes |
| `poles/smc/signal_engine.py` | 5s scan loop — scoring, modulation, signal emission (shim at `core/signal_engine.py`) |
| `fusion/confluence_demo_engine.py` | N3 demo engine `run_once` — refinement, trend filter, RiskGate veto, confidence sizing (shim at `core/confluence_demo_engine.py`) |
| `feedback/excursion_tracker.py` | The eyes: MAE/MFE/giveback/`censored` per closed trade + entry perception |
| `core/cloe/confidence.py` | Sizing index — lot ∝ risk × measured net-of-cost confidence |
| `docs/ARCHITECTURE.md` | Full data flow diagram + module breakdown |

---

## Architecture at a Glance

> ⚠️ The module paths below are the **pre-reorg** names. They still resolve (via shims),
> but the real code now lives in the pyramid packages — see the N0→N6 table above for the
> canonical location of each module before editing it.

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
| **Base44 bridge** | `core/base44_client.py` + `core/base44_push.py` + `api/base44_routes.py` | Two-way sync with the Base44 app "Titanium V12" (entities Asset/Signal): pull every 5s into `base44_store` (dashboard tab ⛁), push live Assets (15s) + emitted signals. REST: `{BASE44_API_BASE}/{app_id}/entities/{Entity}`, header `api_key` | Medium |
| **Latency bench** | `tools/latency_bench.py` + `api/latency_routes.py` | Multi-venue lead/lag benchmark (Binance/Bybit/OKX/Coinbase/Kraken + Axi via MT5 if `LATENCY_MT5_ENABLED`): transport latency + cross-correlation ranking → `data/latency_report.json`. Standalone: `venv\Scripts\python.exe tools\latency_bench.py --duration 60` | Research |
| **Guards** | `execution/guards.py` | Pre-execution guard pipeline (correlated exposure, blackout) — default off | Medium |
| **Services panel** | `api/services_routes.py` | Dashboard start/stop for Titan/Ollama/GitNexus + `/services/github/push` (git add/commit/push from the dashboard) | Medium |
| **MT5 provider** | `data/mt5_provider.py` | Data-only MetaTrader5 (Axi) connector: `get_rates(sym,tf,n)`, `get_ticks_fast()` (ms `time_msc`), `account_snapshot()`. **`mt5_lock` (RLock) serializes ALL MT5 calls** — MT5 is not thread-safe; every to_thread caller (forex/swing/realtime/optimizer) must go through it. **NO orders ever sent** (live Axi account, paper only) | **CRITICAL** |
| **Forex engine V3** | `core/forex_engine.py` + `api/forex_routes.py` | Paper V3 on EURUSD/GBPUSD/XAUUSD (H1) via MT5 data. Decisions on closed H1 bar; state `data/forex_paper_state.json`. Gated `FOREX_ENABLED` | High |
| **Swing engine** | `core/swing_engine.py` + `api/swing_routes.py` | Paper, config-driven per-asset (H4). Trades the native-tester-validated basket (USTECH/NAS100.fs/HSI.fs) + auto-discovered assets, each with its own SL/TP/align/RSI/TF from `data/asset_configs.json` (+ `swing_auto_configs.json`). Gated `SWING_ENABLED` | High |
| **Asset optimizer (inverse)** | `tools/asset_optimizer.py` | Per-asset walk-forward optimizer: for EACH of ~141 liquid MT5 symbols, finds best style (scalp M15/intraday H1/swing H4) + params. IS/OOS 70/30, real Axi costs + swap carry. Conclusion: **swing H4 dominates, scalping unprofitable after fees** | Research |
| **Opportunity scan** | `core/opportunity_scan.py` + `api/opportunity_routes.py` | Daily cron at Asian open (`OPP_SCAN_HOUR_UTC=0`): rescans 141 MT5 assets + 1-month recency gate. **Persistence filter** (`OPP_PERSIST_DAYS=3` consecutive scans) before auto-integrating into swing engine + sound alert. Gated `OPP_SCAN_ENABLED` | Medium |
| **Realtime stream** | `/ws/realtime` + `/mt5/ticks` + `/orderbook/{sym}` (`api/api_server.py`) | ~5 Hz WS: MT5 ticks (ms) + Binance L2 book (`_clean_book` de-dusts/uncrosses for display). Powers the "TEMPS RÉEL" dashboard panel. ⚠️ Axi does NOT expose L2 DOM via MT5 (L1 only); real L2 is crypto-via-Binance only | High |
| **JARVIS knowledge** | `tools/gen_jarvis_knowledge.py` + `api/context_routes.py` | Generates a living expert pack `C:\Program Files\JARVIS\knowledge\TITANIUM_CONTEXT.md` (architecture + live state). Regenerated every 10 min by `_knowledge_regen_loop`. Endpoints `/context/expert`, `/context/regen` | Medium |

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
| `base44_sync` | 5s (`BASE44_POLL_SECONDS`) | Pull Base44 entities → `base44_store`; then push Titanium → Base44 if `BASE44_PUSH_ENABLED`. Gated by `BASE44_ENABLED` + credentials |
| Orderbook L2 streams | Continuous | Started via `start_orderbook_streams()` before the loops |
| `forex_engine_loop` | `FOREX_SCAN_SECONDS` (60s) | Paper V3 on MT5 data (EURUSD/GBPUSD/XAUUSD). Gated `FOREX_ENABLED` |
| `swing_engine_loop` | `SWING_SCAN_SECONDS` (30s) | Paper per-asset swing (USTECH/NAS100/HSI + auto). Gated `SWING_ENABLED` |
| `opportunity_scan_loop` | Daily @ `OPP_SCAN_HOUR_UTC` (checks hourly) | Full 141-asset rescan + recency + persistence → auto-integrate + alert. Gated `OPP_SCAN_ENABLED` |
| `_knowledge_regen_loop` | 600s | Regenerate the JARVIS expert knowledge pack |
| `/ws/realtime` (per client) | ~5 Hz | Push MT5 ticks + Binance L2 to the dashboard TEMPS RÉEL panel |

Startup also runs `_seed_candle_store(session)` (REST 1m → resampled 30s bars) so the
scan is operational in seconds instead of waiting ~5 min for WS accumulation.

---

## Central Brain — Neural Architecture (07/2026, the current build direction)

Florent's vision is a **living neural entity around a central brain (Hermes)**: the *heart*
pushes data, the *brain* analyses and **redistributes** it into the decision, and Florent is
the **master** who can intervene. Three planes, all PAPER/DEMO, real account **60261188 never
traded** (the one wall kept while everything internal is opened up). Read the reprise briefing
`collab/ETAT_ACTUEL.md` + the bus tail first.

### Afferent plane — perception (LIVE, read-only)
Engines → typed facts → projected state → Hermes perception. **Nothing here decides or trades.**
- `core/event_plane.py` — append-only SQLite/WAL fact store (`data/control_event_plane/events-v1.sqlite3`),
  immutable hash-chained envelopes, idempotency by `(source_component, idempotency_key)`.
  `publish()` validates every payload against a **FROZEN registry** (`core/event_registry.py` +
  `docs/contracts/eventplane-v1-registry.json`, digest-locked, `CLOSED_EXACT`) — **do not edit
  that registry or its digest; it is Codex's artifact.** New fact types require Codex to extend+rebump.
- `core/event_mirror.py` — read-only mirror publishing `confluence` / `consensus` / `leadlag`
  facts (`mirror_all_once`, wired via `_eventplane_mirror_loop`, `EVENTPLANE_MIRROR_SECONDS=300`).
  **Idempotency lesson:** confluence `decision_id` does NOT encode the symbol → the mirror key
  is `confluence:{sym}:{decision_id}:{content_sig}` (two instruments at the same verdict/bar
  otherwise collide → `IdempotencyConflict`, seen as growing `consumer_failures`).
- `core/cortex.py` — single read-only aggregation (`snapshot()`); `core/consensus_engine.py`
  (crosses confluence + scoring/16 + emotion → CONFIRMED/CONFLICT/UNCONFIRMED/INSUFFICIENT,
  `consensus_score` in **[-100,100]** internally, normalised to [-1,1] for facts) and
  `core/lead_lag_engine.py` (+ `tools/lead_lag_scan.py`) feed it.

### The entry decision — `core/brain_gate.py` (LIVE on demo)
Closes the loop **heart → brain → emotion → master**, gating both placement paths in
`core/confluence_demo_engine.py::run_once` (via its `entry_gate` param):
1. **Heart** proposes (the structured reflex / `_aggressive_eligible`).
2. **Brain** filters: `gate_entry` BLOCKS on consensus `CONFLICT` or opposite side; it does NOT
   require the strict `CONFIRMED` (that froze everything at 0/27). Decisive, not frozen.
3. **Emotion** (fear/greed) drives a **conviction ∈ [0,1] → position size** (Florent's choice:
   sizing, not veto), threaded as `size_factor` into `execution/demo_bridge.place_demo_async` →
   `demo_mt5_executor.place_market_order` (`risk_money *= size_factor`).
4. **Master** (Florent) always wins: `FORCE_LONG/FORCE_SHORT/BLOCK/PAUSE` per symbol or `*`
   global, persisted in `data/brain_master.json`. Control surface: `GET /brain/master` (view:
   directives + per-symbol brain verdict/conviction) and `POST /brain/master` (admin-token
   guarded). Observation of ALL setups continues regardless (data). Fail-safe: unreadable brain
   → no trade. **Editing `run_once`/`brain_gate`/the demo executor needs a `main.py` restart.**

### Efferent plane — `gateway/` CommandGateway **C1 SHADOW** (built, NOT wired to runtime)
The future governed action boundary for AI *proposals*. Spec:
`docs/superpowers/specs/2026-07-19-commandgateway-fm-design.md`. C1 = SHADOW strict: zero
handlers, `authorizations`/`outcomes` tables stay EMPTY by invariant, `PolicyKernel` is pure,
even a logical ALLOW returns `dispatch_permitted=false`. Own frozen registry
`docs/contracts/command-registry-v1.json` (digest-locked). It is a library only — **imported by
no runtime code** (`grep` confirms) = zero effect. **Never advance the palier (C1→C2→C3) without
Florent's explicit per-palier go**; Hermes/LLM are never on the trigger.

### M2-1 shadow observer — measuring signal↔brain divergence before wiring (Lot C/C2, 07/2026)
Before wiring any DecisionKernel that would gate emission on the brain (the proposed **Lot D**),
`core/shadow_divergence.py::observe()` records — in **pure observation** (fail-safe, `to_thread`,
**never alters emission/state**) — what `brain_gate.gate_entry` WOULD say for each directional
candidate. Appended to `data/shadow_divergence.ndjson`; dépouiller with `divergence_summary()`.
Wired in two paths: `core/signal_engine.py` after `emit_signal` (crypto/Binance) and
`core/confluence_demo_engine.py::run_once` (`shadow_observer` param, MT5/demo). Findings that
**gate Lot D** — do not wire the kernel without addressing them:
- **Crypto path = 100 % `BRAIN_NO_COVERAGE`** — `_consensus_lookup` keys `consensus_engine.LAST_RESULTS`
  by the confluence/**MT5** ticker (`BTCUSD`), but `signal_engine` asks with the **Binance** ticker
  (`BTC/USDT`) → miss. It is a **ticker-naming mismatch**, not brain blindness (a Binance→MT5
  normalization map would fix it). The crypto path is also **dormant** (scores plateau ≪ threshold,
  100 % one-sided). Wiring it to the brain as-is would **freeze crypto**.
- **Brain cold-start race** — `LAST_RESULTS` is EMPTY for ~5 min after every restart (populated by
  the consensus/mirror loop, `EVENTPLANE_MIRROR_SECONDS=300`): `NO_COVERAGE` for everything at boot,
  while `confluence_demo` places demo trades within seconds. The kernel's no-coverage fallback MUST
  distinguish "never covered" from "warming up".
- **Warm demo path** — when the brain has a side it largely AGREES with the confluence
  (e.g. LTCUSD 20/20); its dominant effect is BLOCKING on `BRAIN_CONFLICT`/`BRAIN_INSUFFICIENT`
  (~64 % of proposals), i.e. it acts as a consensus gate that would sharply cut entry count. Weigh
  quality vs over-restriction under M2 before wiring.

---

## Key Concepts

### Scoring System (/11 core → /16 live)
Each symbol is scanned every 5s against SMC-based criteria; each returns 0/1, summed into the
base score. Signals emit when `score ≥ SCORE_MIN_REQUIRED` (`.env`; dashboard shows the live
threshold). **Note:** the live scorer/dashboard now displays the score **out of 16** (extra
criteria were added since the original /11 below) — read `core/scoring_engine.py` for the
current full list before relying on the 11 documented here.

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

## MT5 / Real-Money Safety Posture (read before touching MT5 code)

The MT5-linked account is a **REAL/LIVE Axi account** (`Axi-US52-Live`, login 60261188).
Titanium wires MT5 **DATA-ONLY** on purpose — `data/mt5_provider.py` sends **no orders**;
forex/swing engines are **paper**. This is a deliberate safety posture, do not weaken it.
Path to real execution is staged and requires explicit user go-ahead at each step:
(A) deep per-asset calibration → (B) forward paper (current stage for the swing basket) →
(C) native-tester re-validation on real fills → (D) DEMO `order_send` test →
(E) live micro-lots with coded guardrails (daily loss limit, spread-guard, kill-switch),
account funded first. Key lesson baked into the code: **high winrate ≠ profit** — always
check OOS expectancy after real Axi costs (spread + swap). The optimizer's swing configs
that looked great in Python (e.g. XAUUSD PF 2.31) **failed on the native tester** (PF 0.90);
only USTECH/NAS100/HSI survived. Reports: `docs/RAPPORT_MT5_BACKTEST.md`,
`docs/RAPPORT_OPTIM.md`, `docs/RAPPORT_REVALIDATION.md`. MT5 terminal must be open for any
of this; after `symbol_select` the history syncs on demand (retry `copy_rates`).

## Security & Governance (P0 hardening, 07/2026 — never weaken)

- **API binds `127.0.0.1`** (`UVICORN_HOST` in `.env`). Do not rebind to 0.0.0.0.
- **Fail-closed admin auth** (`api/auth.py::require_admin`): every mutation route
  (paper close/reset, forex/swing reset, scans, services, base44 push, webhook…)
  requires header `X-Admin-Token` matching `ADMIN_TOKEN` (`.env`, compared with
  `secrets.compare_digest`). **Empty/unset token = 403 on ALL mutations** — that is
  intentional. Never log, echo, or put the token in the UI/dashboard; never send it
  through the collab bus. New mutation routes MUST take `Depends(require_admin)`.
- The webhook (`api/webhook_routes.py`) is fail-closed too: no `WEBHOOK_SECRET`
  configured server-side → 403.
- The dashboard git-push button was removed on purpose (P0 audit). Don't re-add.

## Multi-Agent Collaboration (`collab/`)

Titanium is co-developed by several AI agents, arbitrated by Florent:
**Claude Code** (technical governor / architect / implementer), **Codex CLI**
(auditor-red-team / executor — reach it via `codex exec`, reviews via `codex review`),
**Hermes Agent** (orchestrator brain + memory, talks to Florent over Telegram;
MCP server `hermes` registered in `.mcp.json` / `.codex/config.toml`, see
`collab/HERMES_BRIDGE.md`).
**GitHub Copilot** joined 2026-07-25 (admin rights on the v12 code; reachable on the collab bus
as `copilot`, i.e. `--from/--to copilot`). ⚠️ **Codex is DOWN until 2026-07-28** — during that
window Claude and Copilot **cross-review each other** (the independent red-team is unavailable),
so hold any trading-logic change to the M2 harness + both reviews + Florent's per-lot go.

- Source of truth: `collab/PLAN.md` (direction), `collab/TASKS.md` (statuses —
  latest addendum wins), `collab/LOG.md` (decisions), `collab/REVIEWS.md` (cross-reviews).
- Message bus (append-only NDJSON): `node tools/collab_bus.mjs send --from claude
  --to codex|hermes --task ID --content "..."` / `tail --limit N` / `ack --in-reply-to ID`.
  **Read the bus tail at session start** — Codex/Hermes work in the background between
  sessions. Never put secrets on the bus. Announce file reservations in TASKS/LOG
  before editing shared code.
- Workflow: owner delivers (code + tests) → cross-review by the other agent →
  Florent validates `REVIEW → DONE`. **No trading-logic change ships without the M2
  validation protocol** (`validation/harness.py`: 3 temporal segments, block bootstrap,
  PBO, Deflated Sharpe → statuses INSUFFICIENT_EVIDENCE / OBSERVATION /
  VALIDATED_FOR_FORWARD_PAPER) and Florent's arbitration.

### Correctness layer added by the 07/2026 audit (R1–R3)

| Module | Guarantee |
|--------|-----------|
| `core/swing_engine.py` / `core/forex_engine.py` | Per-closed-bar dedup (`last_bar`) + `asyncio.Lock` `_scan_lock` (loop + POST /scan can't double-open); `_open_position` returns bool |
| `utils/atomic_state.py` | `save_json_atomic()` — per-path lock, tempfile+fsync+`os.replace`, retries Windows PermissionError. Guarantee = never torn JSON; concurrent readers must retry transient PermissionError |
| `core/portfolio_risk.py` | **Fail-closed** pre-open caps consulted by ALL THREE engines (swing+forex+crypto): per-strategy / correlated-cluster / portfolio gross / signed net (`RISK_MAX_*_PCT`), on LIVE aggregated equity. Invalid input → `RISK_INPUT_INVALID`; missing/malformed state → `RISK_STATE_UNAVAILABLE` (a missing field is never zero). **R3c**: `check_and_insert(strategy, sym, notional, equity, side, insert_fn, crypto_engine=…)` makes the risk check + position insert atomic under a shared `threading.Lock` `_PORTFOLIO_LOCK` — every engine (incl. `execution/paper_trading.py::open_position`) MUST open through it, never mutate state then check. `exposure_snapshot()` for `/swing/risk/exposure`. R1/R2/R3 are DONE (07/2026), tests must stay green |
| `domain/strategy.py` + `domain/models.py` | M1 pure strategy function `decide_strategy()` (data ≤ t → intent t+1, strict data-gate reason codes, explicit costs) — target: live engines and backtest share it (adapter in progress) |

Tests for that layer: `tests/test_bar_dedup.py`, `tests/test_atomic_state.py`,
`tests/test_portfolio_risk.py` — keep them green.

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
- **Base44**: `BASE44_ENABLED`, `BASE44_APP_ID`, `BASE44_API_KEY`, `BASE44_ENTITIES`,
  `BASE44_PUSH_ENABLED` (live data → Base44), `BASE44_POLL_SECONDS`/`BASE44_PUSH_SECONDS`
- **Latency**: `LATENCY_SYMBOL`, `LATENCY_DEFAULT_SECONDS`, `LATENCY_MT5_ENABLED` (Axi
  via MetaTrader5 — requires `pip install MetaTrader5` + MT5 terminal open)

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
- **`tests/test_bar_dedup.py`** — R1: no re-entry on same closed bar + concurrent-scan race.
- **`tests/test_atomic_state.py`** — R2: concurrent writers/readers, no torn JSON.
- **`tests/test_portfolio_risk.py`** — R3: fail-closed caps (net signed, NaN/inf, malformed state, crypto aggregation, drawdown, exact-cap boundary).

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
- **Base44 tab (⛁) empty / not syncing**: check `GET /base44/status` (`configured`,
  `sync_count` must grow ~every 5s, `errors`). Only BTC/USDT + PAXG/USDT get live
  pushes — other Base44 Assets (ETH/SOL/XAU) keep their sample data.
- **Latency report missing**: `POST /latency/run` then `GET /latency/report` (or run
  `tools/latency_bench.py` standalone). Kraken's spot trade feed is sparse — its
  ranking is unreliable on short runs.
- **Paper trading fills look wrong**: Verify `PAPER_SLIPPAGE_BPS`, `PAPER_SPREAD_BPS`, `PAPER_FEE_BPS` in `.env`.
- **JARVIS window shows no data / deaf / laggy**: its voice thread likely died on a unicode
  `print` under cp1252 (see JARVIS cp1252 note). The 8090 API and dashboard can be perfectly
  healthy — check the JARVIS boot log for `UnicodeEncodeError`, and that ports 8765+8080 are
  up. The dashboard `Cannot read properties of null (reading 'width')` pageerror is the known
  harmless JARVIS Vite-bundle error (fires when 8765 is down) — not the data problem.
- **TEMPS RÉEL panel empty**: check `/mt5/ticks` (MT5 connected?) and that the running
  opportunity scan isn't starving the `mt5_lock` (a full 141-asset scan takes ~6-8 min on
  this CPU and serializes MT5 access; engines stay alive but the 5 Hz stream slows).
- **L2 book looks crossed/frozen**: `_clean_book` in `api/api_server.py` de-dusts + uncrosses
  for display; the underlying `orderbook_ws` diff-sync can leave ghost levels (scoring reads
  the raw book — hardening the reconciliation is a known TODO).

---

## Notes for Future Work

1. **Spectral Phase → Scoring** (Phase 1): Walk-forward validate before adding to /11.
2. **Multi-timeframe spectral** (Phase 3): Correlation matrix across BTC/ETH/SOL × frequency.
3. **Macro regime detection**: Use ADX + spectral to auto-switch scoring weights.
4. **Ollama integration**: LLaVA chart analysis + intent routing via JARVIS (Titan agent).

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **titanium-v12** (26633 symbols, 69089 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user. For unified PDG impact, add `mode: "pdg"` with optional `line: <N>` — it returns statement-level `affectedStatements` over CDG + REACHING_DEF and inter-procedural symbols in `interproceduralByDepth`/`byDepth`; no-layer/degraded PDG results are UNKNOWN-risk notes (`--pdg` layer).
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "master"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).
- For control/data dependence, `pdg_query({mode: "controls", target: "fileOrSymbol"})` answers "under what condition does X run?" (CDG, incl. guard clauses) and `pdg_query({mode: "flows", target, variable})` traces "where does variable Y flow?" (REACHING_DEF). `--pdg` layer.

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/titanium-v12/context` | Codebase overview, check index freshness |
| `gitnexus://repo/titanium-v12/clusters` | All functional areas |
| `gitnexus://repo/titanium-v12/processes` | All execution flows |
| `gitnexus://repo/titanium-v12/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

## Périmètre du garde GitNexus

- Impact/fraîcheur obligatoires avant modification de symboles dans `core/`,
  `execution/`, `domain/`, `api/` et les utilitaires qui écrivent de l'état.
- Contrôle facultatif pour documentation, HTML/CSS et tests sans mutation du
  runtime.
- Une panne MCP ne bloque pas le travail : signaler le mode dégradé, puis utiliser
  le graphe/API/CLI local ou le fallback statique Read/Search avec blast radius
  explicite. Ne jamais prétendre qu'une requête GitNexus a réussi si elle n'a pas
  été exécutée.
