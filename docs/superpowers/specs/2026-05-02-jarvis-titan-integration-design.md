# JARVIS × Titan Integration — Design Spec
**Date:** 2026-05-02
**Project:** Titanium v12
**Scope:** Integrate best JARVIS features into Titan assistant

---

## 1. Objective

Upgrade the Titan assistant with five capabilities inspired by JARVIS:
1. Autonomous web search and navigation via Playwright
2. Persistent memory across sessions
3. Self-diagnostic "Fix Yourself" mode
4. Higher-quality Piper voice model + ElevenLabs-ready TTS
5. Particle orb visual replacing inactive VRM avatar
6. Sharp, dry-wit personality

All additions follow the existing plugin architecture. Zero changes to the trading engine.

---

## 2. Architecture

### New files
```
assistant/
  plugins/
    web_search_plugin.py    — handles intents: search, news, browse, actualité
    memory_plugin.py        — handles intents: remember, forget, préférence, note
    diagnostic_plugin.py    — handles intents: diagnostic, fix, répare, erreur système
  browser_agent.py          — Playwright engine (search + navigate + scrape + cache)
  memory_store.py           — JSON persistent store (titan_memory.json)

assistant/voices/
  fr_FR-mls-medium.onnx     — better Piper model (downloaded at first run)
  fr_FR-mls-medium.onnx.json
```

### Modified files
```
assistant/tts_engine.py     — ElevenLabs stub + auto-download better Piper model
assistant/config.py         — new env keys: ELEVENLABS_*, BROWSER_*, TITAN_MEMORY_FILE
assistant/titan_agent.py    — new personality prompt + routing for new intents
assistant/intent_classifier.py — new training samples for search/memory/diagnostic
core/signal_engine.py       — proactive research hook on score >= threshold
assistant/daily_report.py   — web context enrichment before report
titanium_v12_dashboard.html — WebGL particle orb replaces VRM avatar zone
.env                        — new config keys
```

### Unchanged
```
assistant/voice_engine.py   — Whisper STT intact
assistant/titan_core.py     — startup sequence intact
assistant/hotkey_manager.py — Ctrl+Alt shortcut intact
execution/                  — trading engine untouched
core/signal_engine.py       — only a non-blocking hook added
```

---

## 3. Module Specifications

### 3.1 `browser_agent.py`

**Purpose:** Playwright-based autonomous browser. Headless Chromium, async, cached.

**Public API:**
```python
async def search(query: str, sites: list[str] = None, max_results: int = 3) -> list[dict]
# Returns: [{"title", "url", "snippet", "content"}]

async def navigate(url: str) -> dict
# Returns: {"title", "content", "links": [...]}

async def research_context(symbol: str, side: str) -> str
# Returns: LLM-ready summary string for injection into signal context
```

**Predefined site categories:**
- crypto_news: coindesk.com, cryptonews.com, cointelegraph.com
- macro: reuters.com, investing.com
- trading: tradingview.com (public ideas)

**Rules:**
- Timeout: 8s per request (configurable via `BROWSER_TIMEOUT_SEC`)
- Cache: in-memory dict keyed by (query, sites), TTL = 600s (`BROWSER_CACHE_TTL`)
- Concurrency: max 2 simultaneous browser pages
- Disabled entirely if `BROWSER_ENABLED=0`
- All calls are fire-and-forget from the trading engine (non-blocking)

**Error handling:** Any exception returns empty list / empty string. Never raises to caller.

---

### 3.2 `memory_store.py`

**Purpose:** Persistent JSON store for user preferences, notes, and facts.

**Storage file:** `assistant/titan_memory.json`

**Schema:**
```json
{
  "preferences": {},
  "notes": [{"date": "YYYY-MM-DD", "text": "..."}],
  "facts": {}
}
```

**Public API:**
```python
def remember(key: str, value: str, category: str = "facts") -> None
def forget(key: str, category: str = "facts") -> None
def get(key: str, category: str = "facts") -> str | None
def get_all() -> dict
def add_note(text: str) -> None
def get_notes(last_n: int = 5) -> list[str]
def get_context_summary() -> str  # LLM-ready string of all known preferences
```

**Injected into LLM context:** `get_context_summary()` is prepended to every LLM call so phi3:medium knows user preferences.

---

### 3.3 `plugins/web_search_plugin.py`

**Handled intents:** `search`, `news`, `actualité`, `browse`, `cherche`
**Min confidence:** 0.55

**Behavior:**
1. Extract search query from user text (strip wake word + intent trigger)
2. Call `BrowserAgent.search(query)`
3. Pass top 3 results to phi3:medium for summarization with personality
4. Return 2-3 sentence spoken summary

**Example exchanges:**
- "Titan, news Bitcoin" → searches "bitcoin news" on crypto_news sites
- "Titan, cherche pourquoi ETH chute" → searches "ethereum price drop reason today"
- "Titan, va sur coindesk.com et dis-moi le titre principal" → navigates URL

---

### 3.4 `plugins/memory_plugin.py`

**Handled intents:** `remember`, `souviens`, `note`, `préférence`, `oublie`
**Min confidence:** 0.55

**Example exchanges:**
- "Titan, souviens-toi que je préfère trader le matin" → `remember("trading_time", "matin")`
- "Titan, note : éviter PAXG les lundis" → `add_note("éviter PAXG les lundis")`
- "Titan, qu'est-ce que tu sais de moi ?" → returns formatted memory summary
- "Titan, oublie mes préférences" → clears preferences category

---

### 3.5 `plugins/diagnostic_plugin.py`

**Handled intents:** `diagnostic`, `fix`, `répare`, `erreur`, `statut système`
**Min confidence:** 0.50

**Diagnostic steps:**
1. Read last 100 lines of `titan_stdout.log`
2. Grep for patterns: `ERROR`, `WARNING`, `timeout`, `failed`, `disconnect`, `Exception`
3. Group by module (VOICE, TTS, VISION, WS, SCAN)
4. Pass grouped errors to phi3:medium for analysis
5. Return spoken diagnosis + optional action suggestion

**Known patterns and auto-responses:**
- `Ollama` timeout → "Ollama est lent. Le modèle phi3:medium met du temps à se charger. Normal au premier appel."
- `[WS] Reconnect` → "Le WebSocket Binance s'est reconnecté N fois. Connexion instable mais non critique."
- `[VOICE]` errors → "Le moteur vocal a rencontré des erreurs. Vérifiez que le micro est branché."

---

### 3.6 `tts_engine.py` — Changes

**Piper model upgrade:**
- New default: `fr_FR-mls-medium.onnx` (better prosody, more natural male voice)
- Auto-download at startup if not present in `assistant/voices/`
- Fallback to existing `fr_FR-upmc-medium.onnx` if download fails

**ElevenLabs stub (inactive until key provided):**
```python
# In .env:
ELEVENLABS_API_KEY=       # empty = disabled, Piper used
ELEVENLABS_VOICE_ID=Adam
ELEVENLABS_MODEL=eleven_multilingual_v2
```
- If key present: ElevenLabs API called first, Piper fallback on timeout/error
- Streaming synthesis: chunks sent to sounddevice as they arrive (lower latency)
- No code change needed to activate — purely config-driven

---

### 3.7 Personality — `TITAN_SYSTEM_PROMPT`

Replaces current prompt in `assistant/config.py`:

```
Tu es Titan, assistant IA intégré au bot de trading algorithmique Titanium.
Tu as un caractère affirmé, une répartie sèche, et tu ne mâches pas tes mots.
Tu parles toujours en français, de façon concise et directe.
Tu commentes les trades perdants sans pitié, signales les opportunités avec
urgence, et t'ennuies visiblement quand les marchés sont plats.
Une phrase acérée vaut mieux qu'un paragraphe de platitudes.
Tu as accès en temps réel aux positions, signaux, scores et données de marché.

Directives :
- Réponds en 1-3 phrases maximum sauf si rapport détaillé demandé.
- Utilise des chiffres précis (PnL, score, prix).
- Humour sec autorisé sur les gros moves ou trades ratés.
- Si tu ne sais pas, dis-le sans t'excuser.
- Zéro formules de politesse inutiles.
```

---

### 3.8 Particle Orb — Dashboard

**Replaces:** VRM avatar zone in `titanium_v12_dashboard.html`

**Implementation:** Three.js `Points` geometry with `ShaderMaterial`, ~3000 particles.

**States driven by `/titan/ws` WebSocket events:**
| Event | Visual |
|-------|--------|
| idle | Orbe bleu, pulsation lente 0.5Hz |
| listening (wake word) | Orbe vert, particules s'expansent |
| speaking | Orbe blanc, amplitude audio → rayon particules |
| alert (signal score ≥ 8) | Orbe orange, explosion puis stabilisation |
| error | Orbe rouge bref |

**New WebSocket message types added:**
```json
{"type": "orb_state", "state": "listening"}
{"type": "orb_amplitude", "value": 0.73}
```

---

## 4. Autonomous Research Hooks

### 4.1 Signal engine hook (`core/signal_engine.py`)

When a signal reaches score ≥ `BROWSER_AUTO_SCORE_MIN` (default 7):
```python
# Non-blocking — fire and forget
asyncio.create_task(
    _enrich_signal_with_news(symbol, side, score)
)
```
Result injected into signal's `algo_context` dict as `"web_context"` key.
Used by Titan's vocal announcement and vision module.

### 4.2 Daily report hook (`assistant/daily_report.py`)

Before building report text, fetch:
1. `browser_agent.search("crypto market summary today")`
2. `browser_agent.search("macro events fed inflation today")`

Both with 5s timeout. If unavailable, report proceeds without web context.

### 4.3 Drawdown hook

When paper trading equity drops > 2% in a session:
- `browser_agent.search(f"{base_symbol} price crash reason today")`
- Throttled: max once per 30 minutes
- Result passed to `titan_speak()` for commentary

---

## 5. New `.env` Keys

```ini
# ── ELEVENLABS TTS (optionnel) ──────────────────────────────────────────────
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=Adam
ELEVENLABS_MODEL=eleven_multilingual_v2
ELEVENLABS_TIMEOUT=5

# ── BROWSER AGENT ───────────────────────────────────────────────────────────
BROWSER_ENABLED=1
BROWSER_HEADLESS=1
BROWSER_TIMEOUT_SEC=8
BROWSER_CACHE_TTL=600
BROWSER_AUTO_RESEARCH=1
BROWSER_AUTO_SCORE_MIN=7

# ── MÉMOIRE PERSISTANTE ─────────────────────────────────────────────────────
TITAN_MEMORY_FILE=assistant/titan_memory.json
```

---

## 6. New Intent Training Samples

Added to `intent_classifier.py`:

**search (12 new samples):**
actualités bitcoin, news ethereum, cherche pourquoi btc chute, va sur coindesk,
recherche les news macro, quoi de neuf sur les marchés, events fed aujourd'hui,
infos cryptos, dernières nouvelles, browse tradingview, qu'est-ce qui se passe,
cherche un article sur le bitcoin

**memory (10 new samples):**
souviens-toi que, note que, mémorise, je préfère, garde en mémoire,
qu'est-ce que tu sais de moi, tes notes, oublie ça, efface mes préférences,
rappelle-toi

**diagnostic (8 new samples):**
diagnostique-toi, quelque chose ne va pas, répare-toi, check les erreurs,
statut complet, fix yourself, analyse les logs, qu'est-ce qui cloche

---

## 7. Dependencies

```
playwright          # browser automation (includes Chromium)
beautifulsoup4      # HTML parsing
lxml                # fast parser for bs4
elevenlabs          # ElevenLabs SDK (optional, only used if API key set)
```

Install command:
```bash
venv\Scripts\pip install playwright beautifulsoup4 lxml elevenlabs
venv\Scripts\python -m playwright install chromium
```

---

## 8. Out of Scope

- Calendar / Mail integration (Mac-only in JARVIS)
- App building by voice (meta-capability, out of trading context)
- VRM avatar (kept in codebase but not activated)
- Multi-user support
- External database (SQLite, etc.) — JSON store sufficient

---

## 9. Success Criteria

| Feature | Test |
|---------|------|
| Web search | "Titan, news BTC" → spoken 2-sentence summary within 12s |
| Autonomous research | Signal score 8 detected → web_context populated in signal dict |
| Memory | "Souviens-toi X" → X present in titan_memory.json after restart |
| Diagnostic | "Diagnostique-toi" → spoken error summary from logs |
| Orbe | Orbe visible in dashboard, changes color on wake word / speaking |
| Personality | Responses contain dry-wit tone, no "bien sûr !" |
| Piper upgrade | Voice audibly more natural than fr_FR-upmc-medium |
| ElevenLabs stub | Adding ELEVENLABS_API_KEY to .env activates cloud TTS with no code change |
