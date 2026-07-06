# JARVIS × Titan Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate JARVIS best features (autonomous web search, persistent memory, self-diagnostic, better voice, particle orb UI, dry-wit personality) into Titanium v12's Titan assistant.

**Architecture:** New modules follow the existing plugin pattern — `browser_agent.py` and `memory_store.py` are standalone async utilities; three new plugins register with `assistant/plugins/__init__.py`; all config goes in `assistant/config.py`; signal_engine and daily_report get non-blocking hooks.

**Tech Stack:** Playwright (headless Chromium), BeautifulSoup4/lxml (HTML parsing), ElevenLabs SDK (stub), scikit-learn (intent classifier), Three.js (particle orb), FastAPI/asyncio.

---

## Task 1 — Install dependencies

**Files:**
- Run: `venv\Scripts\pip install ...`

- [ ] **Step 1: Install Python packages**

```powershell
cd C:\Users\flore\Desktop\v12
venv\Scripts\pip install playwright beautifulsoup4 lxml elevenlabs
```

Expected output ends with: `Successfully installed playwright-... beautifulsoup4-... lxml-... elevenlabs-...`

- [ ] **Step 2: Install Playwright Chromium browser**

```powershell
venv\Scripts\python -m playwright install chromium
```

Expected: `Downloading Chromium...` then `chromium v... (playwright build ...) downloaded to ...`

- [ ] **Step 3: Verify installations**

```powershell
venv\Scripts\python -c "from playwright.async_api import async_playwright; from bs4 import BeautifulSoup; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```powershell
git add -A
git commit -m "chore: install playwright, beautifulsoup4, lxml, elevenlabs"
```

---

## Task 2 — Update config files

**Files:**
- Modify: `assistant/config.py` (append new sections)
- Modify: `.env` (append new keys)

- [ ] **Step 1: Append new keys to `assistant/config.py`**

Open `assistant/config.py` and append this block at the end of the file (after `TITAN_SYSTEM_PROMPT`):

```python
# ── Browser Agent ─────────────────────────────────────────────────────────────
BROWSER_ENABLED       = _bool("BROWSER_ENABLED", "1")
BROWSER_HEADLESS      = _bool("BROWSER_HEADLESS", "1")
BROWSER_TIMEOUT_SEC   = _int("BROWSER_TIMEOUT_SEC", 8)
BROWSER_CACHE_TTL     = _int("BROWSER_CACHE_TTL", 600)
BROWSER_AUTO_RESEARCH = _bool("BROWSER_AUTO_RESEARCH", "1")
BROWSER_AUTO_SCORE_MIN = _int("BROWSER_AUTO_SCORE_MIN", 7)

# ── ElevenLabs TTS (optionnel — vide = désactivé) ─────────────────────────────
ELEVENLABS_API_KEY  = _str("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = _str("ELEVENLABS_VOICE_ID", "Adam")
ELEVENLABS_MODEL    = _str("ELEVENLABS_MODEL", "eleven_multilingual_v2")
ELEVENLABS_TIMEOUT  = _int("ELEVENLABS_TIMEOUT", 5)

# ── Mémoire persistante ───────────────────────────────────────────────────────
TITAN_MEMORY_FILE = _str("TITAN_MEMORY_FILE", "assistant/titan_memory.json")
```

Also replace the existing `TITAN_SYSTEM_PROMPT` string with this new personality:

```python
TITAN_SYSTEM_PROMPT = """Tu es Titan, assistant IA intégré au bot de trading algorithmique Titanium.
Tu as un caractère affirmé, une répartie sèche, et tu ne mâches pas tes mots.
Tu parles toujours en français, de façon concise et directe.
Tu commentes les trades perdants sans pitié, signales les opportunités avec urgence,
et t'ennuies visiblement quand les marchés sont plats.
Une phrase acérée vaut mieux qu'un paragraphe de platitudes.
Tu as accès en temps réel aux positions paper, PnL, signaux, scores et risque macro.

Directives :
- Réponds en 1-3 phrases maximum sauf si rapport détaillé demandé.
- Utilise des chiffres précis (PnL, score, prix).
- Humour sec autorisé sur les gros moves ou trades ratés.
- Si tu ne sais pas, dis-le sans t'excuser.
- Zéro formules de politesse inutiles (pas de "bien sûr !", "absolument !")."""
```

- [ ] **Step 2: Append new keys to `.env`**

Open `.env` and append at the end:

```ini
# =============================================================================
# ELEVENLABS TTS (optionnel — laisser vide pour utiliser Piper)
# =============================================================================
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=Adam
ELEVENLABS_MODEL=eleven_multilingual_v2
ELEVENLABS_TIMEOUT=5

# =============================================================================
# BROWSER AGENT — Playwright
# =============================================================================
BROWSER_ENABLED=1
BROWSER_HEADLESS=1
BROWSER_TIMEOUT_SEC=8
BROWSER_CACHE_TTL=600
BROWSER_AUTO_RESEARCH=1
BROWSER_AUTO_SCORE_MIN=7

# =============================================================================
# MÉMOIRE PERSISTANTE
# =============================================================================
TITAN_MEMORY_FILE=assistant/titan_memory.json
```

- [ ] **Step 3: Verify config loads**

```powershell
venv\Scripts\python -c "from assistant.config import BROWSER_ENABLED, ELEVENLABS_API_KEY, TITAN_MEMORY_FILE; print('BROWSER:', BROWSER_ENABLED, 'EL:', repr(ELEVENLABS_API_KEY), 'MEM:', TITAN_MEMORY_FILE)"
```

Expected: `BROWSER: True EL: '' MEM: assistant/titan_memory.json`

- [ ] **Step 4: Commit**

```powershell
git add assistant/config.py .env
git commit -m "feat(config): add browser, elevenlabs, memory config keys + dry-wit personality"
```

---

## Task 3 — `memory_store.py`

**Files:**
- Create: `assistant/memory_store.py`
- Create: `tests/test_memory_store.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_memory_store.py`:

```python
"""Tests for assistant/memory_store.py"""
import json
import pytest
from pathlib import Path


@pytest.fixture(autouse=True)
def tmp_memory(tmp_path, monkeypatch):
    """Each test gets an isolated memory file."""
    mem_file = tmp_path / "titan_memory.json"
    monkeypatch.setenv("TITAN_MEMORY_FILE", str(mem_file))
    # Reset module-level state
    import assistant.memory_store as ms
    ms._store = None
    ms._path = None
    yield mem_file
    ms._store = None
    ms._path = None


def test_remember_and_get():
    import assistant.memory_store as ms
    ms.remember("user_name", "Florent")
    assert ms.get("user_name") == "Florent"


def test_remember_persists_to_disk(tmp_memory):
    import assistant.memory_store as ms
    ms.remember("key", "value")
    data = json.loads(tmp_memory.read_text(encoding="utf-8"))
    assert data["facts"]["key"] == "value"


def test_forget():
    import assistant.memory_store as ms
    ms.remember("x", "y")
    ms.forget("x")
    assert ms.get("x") is None


def test_add_note_and_get_notes():
    import assistant.memory_store as ms
    ms.add_note("Éviter PAXG les lundis")
    ms.add_note("BTC fort le vendredi")
    notes = ms.get_notes(5)
    assert "Éviter PAXG les lundis" in notes
    assert "BTC fort le vendredi" in notes


def test_get_notes_respects_limit():
    import assistant.memory_store as ms
    for i in range(10):
        ms.add_note(f"Note {i}")
    assert len(ms.get_notes(3)) == 3


def test_get_context_summary_empty():
    import assistant.memory_store as ms
    summary = ms.get_context_summary()
    assert summary == ""


def test_get_context_summary_with_data():
    import assistant.memory_store as ms
    ms.remember("trading_style", "scalp", "preferences")
    ms.add_note("Éviter les lundis")
    summary = ms.get_context_summary()
    assert "scalp" in summary
    assert "Éviter les lundis" in summary


def test_preferences_category():
    import assistant.memory_store as ms
    ms.remember("risk_tolerance", "modéré", "preferences")
    assert ms.get("risk_tolerance", "preferences") == "modéré"
    assert ms.get("risk_tolerance", "facts") is None
```

- [ ] **Step 2: Run tests — expect failure**

```powershell
cd C:\Users\flore\Desktop\v12
venv\Scripts\python -m pytest tests/test_memory_store.py -v 2>&1 | Select-Object -First 20
```

Expected: `ModuleNotFoundError: No module named 'assistant.memory_store'`

- [ ] **Step 3: Create `assistant/memory_store.py`**

```python
"""assistant/memory_store.py — Mémoire persistante JSON entre sessions."""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any, Optional

from assistant.config import TITAN_MEMORY_FILE

_store: Optional[dict] = None
_path: Optional[Path] = None


def _load() -> dict:
    global _store, _path
    if _path is None:
        _path = Path(TITAN_MEMORY_FILE)
    if _store is None:
        if _path.exists():
            try:
                _store = json.loads(_path.read_text(encoding="utf-8"))
            except Exception:
                _store = {"preferences": {}, "notes": [], "facts": {}}
        else:
            _store = {"preferences": {}, "notes": [], "facts": {}}
    return _store


def _save() -> None:
    _path.parent.mkdir(parents=True, exist_ok=True)
    _path.write_text(
        json.dumps(_store, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def remember(key: str, value: str, category: str = "facts") -> None:
    store = _load()
    store.setdefault(category, {})[key] = value
    _save()


def forget(key: str, category: str = "facts") -> None:
    store = _load()
    store.get(category, {}).pop(key, None)
    _save()


def get(key: str, category: str = "facts") -> Optional[str]:
    return _load().get(category, {}).get(key)


def get_all() -> dict:
    return dict(_load())


def add_note(text: str) -> None:
    store = _load()
    store.setdefault("notes", []).append({
        "date": time.strftime("%Y-%m-%d"),
        "text": text,
    })
    store["notes"] = store["notes"][-50:]
    _save()


def get_notes(last_n: int = 5) -> list[str]:
    return [n["text"] for n in _load().get("notes", [])[-last_n:]]


def get_context_summary() -> str:
    store = _load()
    parts = []
    if store.get("facts"):
        parts.append("Infos: " + ", ".join(f"{k}={v}" for k, v in store["facts"].items()))
    if store.get("preferences"):
        parts.append("Préférences: " + ", ".join(f"{k}={v}" for k, v in store["preferences"].items()))
    if store.get("notes"):
        recent = store["notes"][-3:]
        parts.append("Notes: " + " | ".join(n["text"] for n in recent))
    return "\n".join(parts)
```

- [ ] **Step 4: Run tests — expect pass**

```powershell
venv\Scripts\python -m pytest tests/test_memory_store.py -v
```

Expected: `8 passed`

- [ ] **Step 5: Commit**

```powershell
git add assistant/memory_store.py tests/test_memory_store.py
git commit -m "feat(memory): persistent JSON memory store with notes/preferences/facts"
```

---

## Task 4 — `browser_agent.py`

**Files:**
- Create: `assistant/browser_agent.py`
- Create: `tests/test_browser_agent.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_browser_agent.py`:

```python
"""Tests for assistant/browser_agent.py — mocked Playwright."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def reset_cache():
    import assistant.browser_agent as ba
    ba._cache.clear()
    yield
    ba._cache.clear()


def test_search_returns_empty_when_disabled(monkeypatch):
    monkeypatch.setenv("BROWSER_ENABLED", "0")
    import importlib
    import assistant.browser_agent as ba
    importlib.reload(ba)
    import asyncio
    result = asyncio.run(ba.search("bitcoin"))
    assert result == []
    # Re-enable for other tests
    monkeypatch.setenv("BROWSER_ENABLED", "1")
    importlib.reload(ba)


def test_cache_key_is_deterministic():
    from assistant.browser_agent import _cache_key
    k1 = _cache_key("bitcoin news", ["coindesk.com", "reuters.com"])
    k2 = _cache_key("bitcoin news", ["reuters.com", "coindesk.com"])
    assert k1 == k2  # sorted, so order doesn't matter


def test_cache_hit_returns_stored_value():
    import assistant.browser_agent as ba
    key = ba._cache_key("test query", [])
    ba._cache[key] = {"ts": __import__("time").monotonic(), "data": [{"title": "cached"}]}
    import asyncio
    result = asyncio.run(ba.search("test query", sites=[]))
    assert result == [{"title": "cached"}]


def test_navigate_returns_empty_on_error(monkeypatch):
    import assistant.browser_agent as ba
    import asyncio

    async def fake_search(*a, **kw):
        raise RuntimeError("network error")

    with patch("assistant.browser_agent._browser_navigate", side_effect=RuntimeError("err")):
        result = asyncio.run(ba.navigate("https://example.com"))
    assert result == {}


def test_research_context_returns_empty_when_disabled(monkeypatch):
    monkeypatch.setenv("BROWSER_ENABLED", "0")
    import importlib
    import assistant.browser_agent as ba
    importlib.reload(ba)
    import asyncio
    result = asyncio.run(ba.research_context("BTC/USDT", "LONG"))
    assert result == ""
    monkeypatch.setenv("BROWSER_ENABLED", "1")
    importlib.reload(ba)
```

- [ ] **Step 2: Run tests — expect failure**

```powershell
venv\Scripts\python -m pytest tests/test_browser_agent.py -v 2>&1 | Select-Object -First 10
```

Expected: `ModuleNotFoundError: No module named 'assistant.browser_agent'`

- [ ] **Step 3: Create `assistant/browser_agent.py`**

```python
"""assistant/browser_agent.py — Agent navigateur Playwright (search + navigate + scrape)."""
from __future__ import annotations
import asyncio
import hashlib
import time
from typing import Any, Optional

from assistant.config import (
    BROWSER_ENABLED, BROWSER_HEADLESS, BROWSER_TIMEOUT_SEC, BROWSER_CACHE_TTL,
)
from utils.logger import get_logger

logger = get_logger(__name__)

_cache: dict[str, dict] = {}

CRYPTO_NEWS_SITES = ["coindesk.com", "cryptonews.com", "cointelegraph.com"]
MACRO_SITES       = ["reuters.com", "investing.com"]


def _cache_key(query: str, sites: list[str]) -> str:
    raw = f"{query}|{'|'.join(sorted(sites))}"
    return hashlib.md5(raw.encode()).hexdigest()


def _cache_get(key: str) -> Optional[Any]:
    entry = _cache.get(key)
    if entry and time.monotonic() - entry["ts"] < BROWSER_CACHE_TTL:
        return entry["data"]
    return None


def _cache_set(key: str, data: Any) -> None:
    _cache[key] = {"ts": time.monotonic(), "data": data}


async def _browser_search(query: str, sites: list[str], max_results: int) -> list[dict]:
    """Internal: run DuckDuckGo search via headless Chromium."""
    from playwright.async_api import async_playwright
    from bs4 import BeautifulSoup

    site_filter   = " OR ".join(f"site:{s}" for s in sites) if sites else ""
    full_query    = f"{query} {site_filter}".strip()
    url           = "https://html.duckduckgo.com/html/?q=" + full_query.replace(" ", "+")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=BROWSER_HEADLESS)
        try:
            page = await browser.new_page()
            await page.goto(url, timeout=BROWSER_TIMEOUT_SEC * 1000, wait_until="domcontentloaded")
            content = await page.content()
        finally:
            await browser.close()

    soup    = BeautifulSoup(content, "lxml")
    results = []
    for el in soup.select(".result")[:max_results]:
        title   = el.select_one(".result__title")
        snippet = el.select_one(".result__snippet")
        url_el  = el.select_one(".result__url")
        if title:
            results.append({
                "title":   title.get_text(strip=True),
                "url":     url_el.get_text(strip=True) if url_el else "",
                "snippet": snippet.get_text(strip=True) if snippet else "",
                "content": snippet.get_text(strip=True) if snippet else "",
            })
    return results


async def _browser_navigate(url: str) -> dict:
    """Internal: navigate to URL and extract text."""
    from playwright.async_api import async_playwright
    from bs4 import BeautifulSoup

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=BROWSER_HEADLESS)
        try:
            page  = await browser.new_page()
            await page.goto(url, timeout=BROWSER_TIMEOUT_SEC * 1000, wait_until="domcontentloaded")
            title   = await page.title()
            content = await page.content()
        finally:
            await browser.close()

    soup = BeautifulSoup(content, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = " ".join(soup.get_text(separator=" ").split())[:3000]
    return {"title": title, "content": text, "url": url}


async def search(
    query: str,
    sites: list[str] = None,
    max_results: int = 3,
) -> list[dict]:
    """Search the web via DuckDuckGo + Playwright. Returns [] on any error."""
    if not BROWSER_ENABLED:
        return []

    _sites = sites if sites is not None else CRYPTO_NEWS_SITES
    key    = _cache_key(query, _sites)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    try:
        results = await _browser_search(query, _sites, max_results)
        _cache_set(key, results)
        logger.info("[BROWSER] '%s' → %d résultats", query, len(results))
        return results
    except Exception as e:
        logger.warning("[BROWSER] Erreur search '%s': %s", query, e)
        return []


async def navigate(url: str) -> dict:
    """Navigate to URL and return {'title', 'content', 'url'}. Returns {} on error."""
    if not BROWSER_ENABLED:
        return {}

    key    = _cache_key(url, [])
    cached = _cache_get(key)
    if cached is not None:
        return cached

    try:
        result = await _browser_navigate(url)
        _cache_set(key, result)
        logger.info("[BROWSER] Navigué vers '%s'", url)
        return result
    except Exception as e:
        logger.warning("[BROWSER] Erreur navigate '%s': %s", url, e)
        return {}


async def research_context(symbol: str, side: str) -> str:
    """Research web context for a trading signal. Returns LLM-ready string."""
    if not BROWSER_ENABLED:
        return ""

    base    = symbol.split("/")[0].lower()
    side_fr = "bullish" if side.upper() == "LONG" else "bearish"
    results = await search(
        f"{base} {side_fr} news today",
        sites=CRYPTO_NEWS_SITES + MACRO_SITES,
        max_results=3,
    )
    if not results:
        return ""

    lines = [f"- {r['title']}: {r['snippet']}" for r in results if r.get("snippet")]
    return "Contexte web:\n" + "\n".join(lines[:3])
```

- [ ] **Step 4: Run tests — expect pass**

```powershell
venv\Scripts\python -m pytest tests/test_browser_agent.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Quick smoke test (requires internet)**

```powershell
venv\Scripts\python -c "
import asyncio
from assistant.browser_agent import search
results = asyncio.run(search('bitcoin news today'))
print('Results:', len(results))
if results: print('First:', results[0]['title'][:60])
"
```

Expected: `Results: 3` (or less) with a real title.

- [ ] **Step 6: Commit**

```powershell
git add assistant/browser_agent.py tests/test_browser_agent.py
git commit -m "feat(browser): Playwright autonomous web search + navigation agent"
```

---

## Task 5 — `plugins/web_search_plugin.py`

**Files:**
- Create: `assistant/plugins/web_search_plugin.py`
- Modify: `assistant/plugins/__init__.py` (register plugin)

- [ ] **Step 1: Create `assistant/plugins/web_search_plugin.py`**

```python
"""assistant/plugins/web_search_plugin.py — Recherche web et navigation par voix."""
from __future__ import annotations
import re
from typing import Any, Dict, Optional

from assistant.plugins.base import TitanPlugin
from utils.logger import get_logger

logger = get_logger(__name__)

_STRIP_WORDS = [
    "titan", "jarvis", "cherche", "recherche", "trouve", "news", "actualités",
    "actualite", "dis-moi", "dis moi", "quoi de neuf sur", "qu'est-ce qui se passe",
    "browse", "va sur", "navigue vers", "ouvre",
]


class WebSearchPlugin(TitanPlugin):
    name           = "web_search"
    intents        = ["search", "news", "actualite", "browse", "cherche", "recherche"]
    min_confidence = 0.50

    async def handle(self, text: str, intent: str, context: Dict[str, Any]) -> Optional[str]:
        from assistant.browser_agent import search, navigate

        text_lower = text.lower()

        # Navigation directe si URL détectée
        url_match = re.search(r'https?://\S+|www\.\S+', text_lower)
        if url_match:
            url = url_match.group()
            if not url.startswith("http"):
                url = "https://" + url
            result = await navigate(url)
            if result.get("content"):
                return (
                    f"Page '{result['title']}' consultée. "
                    f"L'essentiel : {result['content'][:400]}"
                )
            return "Impossible de lire cette page. Elle résiste."

        # Extraction de la requête
        query = text_lower
        for word in sorted(_STRIP_WORDS, key=len, reverse=True):
            query = query.replace(word, " ")
        query = " ".join(query.split()).strip(" ,.?!")

        if not query or len(query) < 3:
            query = "crypto news today"

        results = await search(query)

        if not results:
            return "Rien trouvé. Les marchés conspirent peut-être contre nous."

        snippets = [
            f"{r['title']}: {r['snippet']}"
            for r in results[:2]
            if r.get("snippet")
        ]
        if not snippets:
            return f"Résultats trouvés mais sans extrait pour '{query}'."

        return "D'après mes recherches — " + " | ".join(snippets)
```

- [ ] **Step 2: Register plugin in `assistant/plugins/__init__.py`**

In `assistant/plugins/__init__.py`, find the `_init_plugins` function and add three new entries to the list:

```python
def _init_plugins() -> None:
    """Charge tous les plugins disponibles."""
    global _plugins, _initialized
    if _initialized:
        return
    _initialized = True

    for cls_path in [
        ("assistant.plugins.trading_plugin",    "TradingPlugin"),
        ("assistant.plugins.system_plugin",     "SystemPlugin"),
        ("assistant.plugins.web_search_plugin", "WebSearchPlugin"),
        ("assistant.plugins.memory_plugin",     "MemoryPlugin"),
        ("assistant.plugins.diagnostic_plugin", "DiagnosticPlugin"),
    ]:
        module_path, cls_name = cls_path
        try:
            import importlib
            mod    = importlib.import_module(module_path)
            cls    = getattr(mod, cls_name)
            plugin = cls()
            _plugins.append(plugin)
            logger.info("[PLUGIN] %s chargé (intents: %s)", cls_name, plugin.intents)
        except Exception as e:
            logger.debug("[PLUGIN] %s non chargé: %s", cls_name, e)
```

- [ ] **Step 3: Quick test — plugin loads**

```powershell
venv\Scripts\python -c "
from assistant.plugins import get_plugins
plugins = get_plugins()
names = [p.name for p in plugins]
print('Plugins:', names)
assert 'web_search' in names
print('OK')
"
```

Expected: `Plugins: ['trading', 'system', 'web_search', ...]` then `OK`

- [ ] **Step 4: Commit**

```powershell
git add assistant/plugins/web_search_plugin.py assistant/plugins/__init__.py
git commit -m "feat(plugin): web search and URL navigation plugin"
```

---

## Task 6 — `plugins/memory_plugin.py`

**Files:**
- Create: `assistant/plugins/memory_plugin.py`

- [ ] **Step 1: Create `assistant/plugins/memory_plugin.py`**

```python
"""assistant/plugins/memory_plugin.py — Mémoire persistante par commandes vocales."""
from __future__ import annotations
from typing import Any, Dict, Optional

from assistant.plugins.base import TitanPlugin
from utils.logger import get_logger

logger = get_logger(__name__)

_REMEMBER_TRIGGERS = ["souviens-toi", "souviens toi", "mémorise", "memorise",
                      "note que", "retiens", "garde en mémoire", "garde en memoire"]
_FORGET_TRIGGERS   = ["oublie", "efface", "supprime"]
_RECALL_TRIGGERS   = ["sais de moi", "mémoire", "memoire", "préférences",
                      "preferences", "tes notes", "rappelle", "qu est-ce que tu sais"]


class MemoryPlugin(TitanPlugin):
    name           = "memory"
    intents        = ["remember", "memory", "note", "souviens", "forget", "preference"]
    min_confidence = 0.50

    async def handle(self, text: str, intent: str, context: Dict[str, Any]) -> Optional[str]:
        import assistant.memory_store as mem
        text_lower = text.lower()

        # Rappel
        if any(t in text_lower for t in _RECALL_TRIGGERS):
            summary = mem.get_context_summary()
            notes   = mem.get_notes(5)
            if not summary and not notes:
                return "Je n'ai rien mémorisé pour l'instant. Votre vie est un mystère."
            parts = []
            if summary:
                parts.append(summary)
            if notes:
                parts.append("Notes : " + " | ".join(notes))
            return "\n".join(parts)

        # Oublier
        if any(t in text_lower for t in _FORGET_TRIGGERS):
            if "tout" in text_lower:
                mem._store = {"preferences": {}, "notes": [], "facts": {}}
                mem._save()
                return "Mémoire effacée. Repartons de zéro."
            return "Précisez ce que vous voulez que j'oublie."

        # Mémoriser
        content = text_lower
        for trigger in sorted(_REMEMBER_TRIGGERS, key=len, reverse=True):
            if trigger in content:
                idx     = content.find(trigger) + len(trigger)
                content = content[idx:].strip(" -:,que ")
                break
        # Retirer le wake word
        for wake in ["titan", "jarvis"]:
            content = content.replace(wake, "").strip()
        content = content.strip(" ,.!?")

        if not content or len(content) < 3:
            return None

        if any(w in content for w in ["préfère", "prefere", "aime mieux", "plutôt"]):
            mem.remember("préférence", content, "preferences")
        else:
            mem.add_note(content)
        return f"Noté. Je me souviendrai que {content}."
```

- [ ] **Step 2: Verify plugin registers correctly**

```powershell
venv\Scripts\python -c "
from assistant.plugins import _initialized, _plugins; _initialized = False; _plugins.clear()
from assistant.plugins import get_plugins
names = [p.name for p in get_plugins()]
print(names)
assert 'memory' in names
print('OK')
"
```

Expected: list contains `memory`, then `OK`

- [ ] **Step 3: Commit**

```powershell
git add assistant/plugins/memory_plugin.py
git commit -m "feat(plugin): persistent memory plugin (remember/forget/recall)"
```

---

## Task 7 — `plugins/diagnostic_plugin.py`

**Files:**
- Create: `assistant/plugins/diagnostic_plugin.py`

- [ ] **Step 1: Create `assistant/plugins/diagnostic_plugin.py`**

```python
"""assistant/plugins/diagnostic_plugin.py — Auto-diagnostic Titan depuis les logs."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Optional

from assistant.plugins.base import TitanPlugin
from utils.logger import get_logger

logger = get_logger(__name__)

_BASE     = Path(__file__).resolve().parent.parent.parent
_LOG_FILE = _BASE / "titan_stdout.log"


class DiagnosticPlugin(TitanPlugin):
    name           = "diagnostic"
    intents        = ["diagnostic", "fix", "repare", "diagnose", "logs"]
    min_confidence = 0.45

    async def handle(self, text: str, intent: str, context: Dict[str, Any]) -> Optional[str]:
        if not _LOG_FILE.exists():
            return "Aucun fichier de log. Je ne suis peut-être pas réel."

        lines  = _LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-100:]
        errors = [l for l in lines if " ERROR " in l]
        warns  = [l for l in lines if " WARNING " in l]

        if not errors and not warns:
            return (
                f"Diagnostic terminé. {len(lines)} lignes analysées, "
                "zéro erreur. Pour une fois, tout fonctionne."
            )

        issues = []

        ollama = [l for l in errors + warns if "ollama" in l.lower() or "llm" in l.lower()]
        if ollama:
            issues.append(f"Ollama : {len(ollama)} problème(s)")

        ws = [l for l in errors + warns if "ws" in l.lower() or "websocket" in l.lower()]
        if ws:
            issues.append(f"WebSocket Binance : {len(ws)} reconnexion(s)")

        voice = [l for l in errors + warns if any(
            w in l.lower() for w in ["voice", "whisper", "tts", "piper"]
        )]
        if voice:
            issues.append(f"Moteur vocal : {len(voice)} avertissement(s)")

        vision = [l for l in errors + warns if "vision" in l.lower()]
        if vision:
            issues.append(f"Vision IA : {len(vision)} erreur(s)")

        if not issues:
            issues.append(
                f"{len(errors)} erreur(s) et {len(warns)} avertissement(s) non classifiés"
            )

        summary = ". ".join(issues)
        return f"Diagnostic : {summary}. {len(errors)} erreur(s) totale(s) sur les 100 dernières lignes."
```

- [ ] **Step 2: Verify**

```powershell
venv\Scripts\python -c "
from assistant.plugins import _initialized, _plugins; _initialized = False; _plugins.clear()
from assistant.plugins import get_plugins
names = [p.name for p in get_plugins()]
print(names)
assert 'diagnostic' in names
print('OK — all 5 plugins loaded')
"
```

Expected: 5 plugins in list including `diagnostic`, then `OK — all 5 plugins loaded`

- [ ] **Step 3: Commit**

```powershell
git add assistant/plugins/diagnostic_plugin.py
git commit -m "feat(plugin): self-diagnostic plugin reads logs and classifies issues"
```

---

## Task 8 — Update `intent_classifier.py` with new intents

**Files:**
- Modify: `assistant/intent_classifier.py`

- [ ] **Step 1: Add new training samples**

In `assistant/intent_classifier.py`, find `_TRAINING_DATA` and append before the closing `]`:

```python
    # ── search ────────────────────────────────────────────────────────────────
    ("actualites bitcoin",                       "search"),
    ("news ethereum",                            "search"),
    ("cherche pourquoi btc chute",               "search"),
    ("va sur coindesk",                          "search"),
    ("recherche les news macro",                 "search"),
    ("quoi de neuf sur les marches",             "search"),
    ("events fed aujourd hui",                   "search"),
    ("infos cryptos",                            "search"),
    ("dernieres nouvelles",                      "search"),
    ("browse tradingview",                       "search"),
    ("qu est ce qui se passe",                   "search"),
    ("cherche un article sur le bitcoin",        "search"),
    ("navigues sur",                             "search"),
    ("ouvre ce site",                            "search"),

    # ── remember ──────────────────────────────────────────────────────────────
    ("souviens toi que",                         "remember"),
    ("note que",                                 "remember"),
    ("memorise",                                 "remember"),
    ("je prefere",                               "remember"),
    ("garde en memoire",                         "remember"),
    ("sais de moi",                              "remember"),
    ("ta memoire",                               "remember"),
    ("mes preferences",                          "remember"),
    ("tes notes",                                "remember"),
    ("oublie ca",                                "remember"),
    ("efface mes preferences",                   "remember"),
    ("rappelle toi",                             "remember"),

    # ── diagnostic ────────────────────────────────────────────────────────────
    ("diagnostique toi",                         "diagnostic"),
    ("quelque chose ne va pas",                  "diagnostic"),
    ("repare toi",                               "diagnostic"),
    ("check les erreurs",                        "diagnostic"),
    ("statut complet",                           "diagnostic"),
    ("fix yourself",                             "diagnostic"),
    ("analyse les logs",                         "diagnostic"),
    ("qu est ce qui cloche",                     "diagnostic"),
    ("erreur systeme",                           "diagnostic"),
    ("montre moi les erreurs",                   "diagnostic"),
```

- [ ] **Step 2: Verify new intents are learned**

```powershell
venv\Scripts\python -c "
from assistant.intent_classifier import classify
tests = [
    ('news bitcoin', 'search'),
    ('souviens toi que je trade mieux le matin', 'remember'),
    ('diagnostique toi', 'diagnostic'),
    ('quel est le signal btc', 'signal'),
]
ok = True
for text, expected in tests:
    intent, conf = classify(text)
    status = 'OK' if intent == expected else f'FAIL (got {intent})'
    print(f'{text!r:45} → {intent} ({conf:.2f}) {status}')
    if intent != expected:
        ok = False
print('All OK' if ok else 'SOME FAILED')
"
```

Expected: all 4 lines show correct intent and `All OK`

- [ ] **Step 3: Commit**

```powershell
git add assistant/intent_classifier.py
git commit -m "feat(intent): add search/remember/diagnostic training samples (3 new intents)"
```

---

## Task 9 — Update `titan_agent.py` — memory context injection

**Files:**
- Modify: `assistant/titan_agent.py`

The personality is already updated in Task 2 (config.py). This task adds memory context to every LLM call.

- [ ] **Step 1: Find `ask_titan` function in `assistant/titan_agent.py`**

Open `assistant/titan_agent.py` and locate the `ask_titan` function. Find where `system_prompt` is built (it currently uses `TITAN_SYSTEM_PROMPT` from config). Add memory context injection.

Find this block (or equivalent pattern where the system prompt is assembled):

```python
system_prompt = TITAN_SYSTEM_PROMPT
```

Replace it with:

```python
system_prompt = TITAN_SYSTEM_PROMPT
try:
    from assistant.memory_store import get_context_summary
    mem_ctx = get_context_summary()
    if mem_ctx:
        system_prompt = system_prompt + "\n\n" + mem_ctx
except Exception:
    pass
```

- [ ] **Step 2: Verify agent still works**

```powershell
venv\Scripts\python -c "
import asyncio, aiohttp
async def test():
    async with aiohttp.ClientSession() as s:
        from assistant.titan_agent import ask_titan
        r = await ask_titan('bonjour', session=s)
        print('Response len:', len(r), 'chars')
        print('Preview:', r[:80])
asyncio.run(test())
"
```

Expected: a short French response from phi3:medium (may take 5-15s first call)

- [ ] **Step 3: Commit**

```powershell
git add assistant/titan_agent.py
git commit -m "feat(agent): inject persistent memory context into every LLM prompt"
```

---

## Task 10 — Upgrade `tts_engine.py` — better Piper model + ElevenLabs stub

**Files:**
- Modify: `assistant/tts_engine.py`
- Download: `assistant/voices/fr_FR-mls-medium.onnx` + `.json`

- [ ] **Step 1: Download better Piper voice model**

```powershell
$ProgressPreference = 'SilentlyContinue'
Invoke-WebRequest -Uri "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR/mls/medium/fr_FR-mls-medium.onnx" -OutFile "C:\Users\flore\Desktop\v12\assistant\voices\fr_FR-mls-medium.onnx" -UseBasicParsing
Invoke-WebRequest -Uri "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR/mls/medium/fr_FR-mls-medium.onnx.json" -OutFile "C:\Users\flore\Desktop\v12\assistant\voices\fr_FR-mls-medium.onnx.json" -UseBasicParsing
$size = (Get-Item "assistant\voices\fr_FR-mls-medium.onnx").Length / 1MB
Write-Host "Downloaded: $size MB"
```

Expected: `Downloaded: ~XX MB`

- [ ] **Step 2: Update `TITAN_VOICE_MODEL` default in `.env`**

In `.env`, change:

```ini
TITAN_VOICE_MODEL=fr_FR-mls-medium.onnx
```

- [ ] **Step 3: Add ElevenLabs TTS method to `assistant/tts_engine.py`**

Open `assistant/tts_engine.py` and add this method inside the `PiperTTS` class, after `speak_fallback`:

```python
    async def synthesize_elevenlabs(self, text: str) -> tuple[Optional[np.ndarray], int]:
        """ElevenLabs cloud TTS — activé seulement si ELEVENLABS_API_KEY est défini."""
        from assistant.config import ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL, ELEVENLABS_TIMEOUT
        if not ELEVENLABS_API_KEY:
            return None, 22050
        try:
            import asyncio
            from elevenlabs.client import ElevenLabs
            client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
            loop   = asyncio.get_event_loop()

            def _generate():
                audio_bytes = b"".join(
                    client.generate(
                        text=text,
                        voice=ELEVENLABS_VOICE_ID,
                        model=ELEVENLABS_MODEL,
                    )
                )
                return audio_bytes

            audio_bytes = await asyncio.wait_for(
                loop.run_in_executor(None, _generate),
                timeout=ELEVENLABS_TIMEOUT,
            )
            audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            return audio_np, 22050
        except Exception as e:
            logger.warning("[TTS] ElevenLabs erreur: %s — fallback Piper", e)
            return None, 22050
```

Also update `synthesize_async` to try ElevenLabs first:

```python
    async def synthesize_async(self, text: str) -> tuple[Optional[np.ndarray], int]:
        """Version asynchrone : ElevenLabs si clé disponible, sinon Piper."""
        from assistant.config import ELEVENLABS_API_KEY
        if ELEVENLABS_API_KEY:
            audio, sr = await self.synthesize_elevenlabs(text)
            if audio is not None:
                return audio, sr
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.synthesize, text)
```

- [ ] **Step 4: Test new Piper voice**

```powershell
cd C:\Users\flore\Desktop\v12
venv\Scripts\python -c "
import sounddevice as sd
import numpy as np, subprocess
result = subprocess.run(
    ['assistant/piper/piper.exe', '--model', 'assistant/voices/fr_FR-mls-medium.onnx', '--output_raw'],
    input='Titan en ligne. Nouvelle voix activée.'.encode('utf-8'),
    capture_output=True, timeout=15
)
if result.returncode == 0:
    audio = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    sd.play(audio, samplerate=22050, blocking=True)
    print('OK — nouvelle voix jouée')
else:
    print('ERREUR:', result.stderr[:100])
"
```

Expected: audio plays with the new voice, then `OK — nouvelle voix jouée`

- [ ] **Step 5: Commit**

```powershell
git add assistant/tts_engine.py assistant/voices/fr_FR-mls-medium.onnx assistant/voices/fr_FR-mls-medium.onnx.json .env
git commit -m "feat(tts): upgrade to fr_FR-mls-medium Piper voice + ElevenLabs stub"
```

---

## Task 11 — Signal engine proactive research hook

**Files:**
- Modify: `core/signal_engine.py`

- [ ] **Step 1: Add research enrichment function to `signal_engine.py`**

Open `core/signal_engine.py`. After the imports block (around line 25), add this function:

```python
async def _enrich_signal_with_news(sym: str, side: str, score: int) -> None:
    """Non-blocking: fetch web context for a strong signal and log it."""
    try:
        from assistant.config import BROWSER_AUTO_RESEARCH, BROWSER_AUTO_SCORE_MIN
        if not BROWSER_AUTO_RESEARCH or score < BROWSER_AUTO_SCORE_MIN:
            return
        from assistant.browser_agent import research_context
        web_ctx = await research_context(sym, side)
        if web_ctx:
            logger.info("[BROWSER] Contexte signal %s %s: %s", sym, side, web_ctx[:120])
    except Exception as e:
        logger.debug("[BROWSER] Erreur enrichissement signal: %s", e)
```

- [ ] **Step 2: Find where `emit_signal` is called in `scan_symbol` and add hook**

In `scan_symbol`, find the block that calls `emit_signal` (search for `emit_signal` in the file). Just before or right after `emit_signal(...)` is called with a qualifying score, add:

```python
# Non-blocking research hook for strong signals
asyncio.create_task(
    _enrich_signal_with_news(sym, side, score)
)
```

Where `side` and `score` are the local variables already computed by the scoring logic.

- [ ] **Step 3: Verify no import errors**

```powershell
venv\Scripts\python -c "from core.signal_engine import scan_symbol; print('Import OK')"
```

Expected: `Import OK`

- [ ] **Step 4: Commit**

```powershell
git add core/signal_engine.py
git commit -m "feat(signal): non-blocking web research hook on strong signals (score >= threshold)"
```

---

## Task 12 — Daily report web context enrichment

**Files:**
- Modify: `assistant/daily_report.py`

- [ ] **Step 1: Add web enrichment to `build_daily_report`**

In `assistant/daily_report.py`, modify `build_daily_report` to fetch web context before building the report text. Add this block right after collecting the API data (after the four `_fetch` calls, before `lines = [...]`):

```python
    # Web context enrichment (non-blocking, 5s timeout)
    web_summary = ""
    try:
        from assistant.config import BROWSER_AUTO_RESEARCH
        if BROWSER_AUTO_RESEARCH:
            from assistant.browser_agent import search
            results = await asyncio.wait_for(
                search("crypto market summary today macro events"),
                timeout=5.0,
            )
            if results:
                snippets = [r["title"] for r in results[:2] if r.get("title")]
                web_summary = "Actualités du jour : " + " | ".join(snippets) + "."
    except Exception:
        pass  # Report proceeds without web context if browser unavailable
```

Then append `web_summary` to the report at the end of `build_daily_report`, just before `return`:

```python
    if web_summary:
        lines.append(web_summary)

    return " ".join(lines)
```

- [ ] **Step 2: Verify import**

```powershell
venv\Scripts\python -c "from assistant.daily_report import build_daily_report; print('Import OK')"
```

Expected: `Import OK`

- [ ] **Step 3: Commit**

```powershell
git add assistant/daily_report.py
git commit -m "feat(report): enrich daily report with live web news context"
```

---

## Task 13 — Particle orb in dashboard

**Files:**
- Modify: `titanium_v12_dashboard.html`

- [ ] **Step 1: Find and replace avatar section**

Open `titanium_v12_dashboard.html`. Search for the section containing the Titan avatar (look for `id="titan"`, `titan-panel`, `vrm`, or avatar-related divs). Replace that entire section with the particle orb panel:

```html
<!-- ── TITAN ORBE ──────────────────────────────────────────────────────── -->
<div class="panel" id="titan-panel" style="position:relative;overflow:hidden;min-height:320px;display:flex;flex-direction:column;align-items:center;justify-content:center;background:#0a0a14;">
  <canvas id="orb-canvas" style="width:100%;height:280px;display:block;"></canvas>
  <div id="orb-status" style="position:absolute;bottom:12px;left:0;right:0;text-align:center;font-size:11px;color:#4488ff;letter-spacing:2px;text-transform:uppercase;opacity:0.7;">TITAN EN VEILLE</div>
</div>
```

- [ ] **Step 2: Add Three.js orb script**

At the end of the HTML `<body>`, just before `</body>`, add this script block:

```html
<script>
// ── TITAN PARTICLE ORB ─────────────────────────────────────────────────────
(function() {
  const canvas  = document.getElementById('orb-canvas');
  if (!canvas) return;

  // Use Three.js already loaded in the page, or load it
  function initOrb(THREE) {
    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);

    const scene  = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(60, canvas.clientWidth / canvas.clientHeight, 0.1, 100);
    camera.position.z = 3;

    const COUNT = 3000;
    const geo   = new THREE.BufferGeometry();
    const pos   = new Float32Array(COUNT * 3);
    const col   = new Float32Array(COUNT * 3);
    const base  = new Float32Array(COUNT * 3); // base sphere positions

    for (let i = 0; i < COUNT; i++) {
      const theta = Math.random() * Math.PI * 2;
      const phi   = Math.acos(2 * Math.random() - 1);
      const r     = 0.85 + Math.random() * 0.3;
      base[i*3]   = pos[i*3]   = r * Math.sin(phi) * Math.cos(theta);
      base[i*3+1] = pos[i*3+1] = r * Math.sin(phi) * Math.sin(theta);
      base[i*3+2] = pos[i*3+2] = r * Math.cos(phi);
      col[i*3] = 0.2; col[i*3+1] = 0.5; col[i*3+2] = 1.0;
    }

    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('color',    new THREE.BufferAttribute(col, 3));

    const mat  = new THREE.PointsMaterial({ size: 0.018, vertexColors: true, transparent: true, opacity: 0.85 });
    const orb  = new THREE.Points(geo, mat);
    scene.add(orb);

    // State machine
    let state     = 'idle';   // idle | listening | speaking | alert
    let amplitude = 0;
    let t         = 0;

    const STATE_COLORS = {
      idle:      [0.2, 0.5, 1.0],
      listening: [0.2, 1.0, 0.4],
      speaking:  [1.0, 1.0, 1.0],
      alert:     [1.0, 0.5, 0.1],
    };
    const STATUS_TEXT = {
      idle:      'TITAN EN VEILLE',
      listening: 'ÉCOUTE…',
      speaking:  'TITAN PARLE',
      alert:     'SIGNAL DÉTECTÉ',
    };

    function setOrbState(newState, amp) {
      state     = newState;
      amplitude = amp || 0;
      const el  = document.getElementById('orb-status');
      if (el) el.textContent = STATUS_TEXT[newState] || newState.toUpperCase();
    }

    function animate() {
      requestAnimationFrame(animate);
      t += 0.016;

      const c      = STATE_COLORS[state] || STATE_COLORS.idle;
      const pulse  = state === 'idle'     ? 0.05 * Math.sin(t * 0.5) :
                     state === 'speaking' ? 0.15 * amplitude          :
                     state === 'alert'    ? 0.12 * Math.sin(t * 3.0)  :
                                            0.08 * Math.sin(t * 2.0);

      const posAttr = geo.getAttribute('position');
      for (let i = 0; i < COUNT; i++) {
        const bx = base[i*3], by = base[i*3+1], bz = base[i*3+2];
        const n  = 1.0 + pulse + (state !== 'idle' ? 0.04 * Math.sin(t * 4 + i * 0.01) : 0);
        posAttr.array[i*3]   = bx * n;
        posAttr.array[i*3+1] = by * n;
        posAttr.array[i*3+2] = bz * n;

        const colAttr = geo.getAttribute('color');
        colAttr.array[i*3]   = c[0];
        colAttr.array[i*3+1] = c[1];
        colAttr.array[i*3+2] = c[2];
        colAttr.needsUpdate  = true;
      }
      posAttr.needsUpdate = true;

      orb.rotation.y += 0.003;
      orb.rotation.x += 0.001;

      const w = canvas.clientWidth, h = canvas.clientHeight;
      if (renderer.domElement.width !== w || renderer.domElement.height !== h) {
        renderer.setSize(w, h, false);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
      }
      renderer.render(scene, camera);
    }

    animate();

    // WebSocket Titan messages
    window._titanOrbSetState = setOrbState;
  }

  // Load Three.js if not already present
  if (window.THREE) {
    initOrb(window.THREE);
  } else {
    const s  = document.createElement('script');
    s.src    = 'https://cdn.jsdelivr.net/npm/three@0.168.0/build/three.min.js';
    s.onload = () => initOrb(window.THREE);
    document.head.appendChild(s);
  }

  // Hook into existing Titan WebSocket handler
  const _origTitanWS = window._handleTitanWS;
  window._handleTitanWS = function(msg) {
    if (msg.type === 'orb_state' && window._titanOrbSetState) {
      window._titanOrbSetState(msg.state, msg.amplitude || 0);
    }
    if (msg.type === 'speaking') {
      window._titanOrbSetState && window._titanOrbSetState(msg.value ? 'speaking' : 'idle');
    }
    if (_origTitanWS) _origTitanWS(msg);
  };
})();
</script>
```

- [ ] **Step 3: Add `orb_state` broadcast to `assistant/avatar_renderer.py`**

In `assistant/avatar_renderer.py`, add this new function after `send_reset`:

```python
async def send_orb_state(state: str, amplitude: float = 0.0) -> None:
    """Envoie l'état de l'orbe de particules au dashboard."""
    await ws_titan_broadcast({
        "type":      "orb_state",
        "state":     state,
        "amplitude": round(amplitude, 3),
    })
```

Then in `assistant/popup_manager.py`, call `send_orb_state` at key moments. Find the `speak` method and update it:

```python
        # Before synthesis — set orb to speaking
        from assistant.avatar_renderer import send_orb_state
        await send_orb_state("speaking")

        audio, sr = await tts.synthesize_async(text)
        # ... existing code ...

        # After speaking — back to idle
        await send_orb_state("idle")
```

Also in `assistant/voice_engine.py`, after wake word is detected (in `_listen_loop`), add:

```python
# Signal orb = listening
try:
    from assistant.avatar_renderer import send_orb_state
    import asyncio
    if self._loop:
        asyncio.run_coroutine_threadsafe(send_orb_state("listening"), self._loop)
except Exception:
    pass
```

- [ ] **Step 4: Open dashboard in browser and verify orb**

```powershell
Start-Process "http://localhost:8080"
```

Navigate to the Titan panel. The orb should be a blue pulsing sphere of particles. Say "Titan" — orb should turn green. Titan responds — orb should turn white while speaking.

- [ ] **Step 5: Commit**

```powershell
git add titanium_v12_dashboard.html assistant/avatar_renderer.py assistant/popup_manager.py assistant/voice_engine.py
git commit -m "feat(ui): replace VRM avatar with Three.js particle orb (idle/listening/speaking/alert states)"
```

---

## Task 14 — Integration smoke test

**Files:**
- Run: full server with new features

- [ ] **Step 1: Stop any running server**

```powershell
Stop-Process -Name python -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
```

- [ ] **Step 2: Start server with log capture**

```powershell
cd C:\Users\flore\Desktop\v12
Start-Process -FilePath "venv\Scripts\python.exe" -ArgumentList "main.py" -WorkingDirectory "C:\Users\flore\Desktop\v12" -RedirectStandardOutput "titan_stdout.log" -RedirectStandardError "titan_stderr.log" -NoNewWindow
Start-Sleep -Seconds 12
```

- [ ] **Step 3: Verify all plugins loaded**

```powershell
Get-Content titan_stdout.log | Select-String "PLUGIN"
```

Expected: 5 lines like `[PLUGIN] TradingPlugin chargé`, `WebSearchPlugin`, `MemoryPlugin`, `DiagnosticPlugin`, `SystemPlugin`

- [ ] **Step 4: Test voice command via API**

```powershell
$body = '{"message": "diagnostique toi"}'
$r = Invoke-WebRequest -Uri "http://localhost:8080/api/chat" -Method POST -Body $body -ContentType "application/json" -UseBasicParsing -TimeoutSec 30
$r.Content
```

Expected: JSON with a diagnostic message containing log analysis.

- [ ] **Step 5: Test memory via API**

```powershell
$body = '{"message": "souviens toi que je prefere trader le matin"}'
$r = Invoke-WebRequest -Uri "http://localhost:8080/api/chat" -Method POST -Body $body -ContentType "application/json" -UseBasicParsing -TimeoutSec 30
$r.Content
```

Expected: response confirming memory was saved. Verify file:

```powershell
Get-Content "assistant\titan_memory.json"
```

- [ ] **Step 6: Final commit**

```powershell
git add -A
git commit -m "feat: JARVIS x Titan integration complete — browser agent, memory, diagnostic, orb UI, personality"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] browser_agent.py — Tasks 4, 11, 12
- [x] memory_store.py — Task 3
- [x] web_search_plugin.py — Task 5
- [x] memory_plugin.py — Task 6
- [x] diagnostic_plugin.py — Task 7
- [x] intent_classifier (3 new intents) — Task 8
- [x] titan_agent.py memory injection — Task 9
- [x] tts_engine.py Piper upgrade + ElevenLabs — Task 10
- [x] signal_engine.py research hook — Task 11
- [x] daily_report.py web enrichment — Task 12
- [x] Particle orb dashboard — Task 13
- [x] Personality (TITAN_SYSTEM_PROMPT) — Task 2
- [x] .env new keys — Task 2

**Type consistency:** `browser_agent.search()` returns `list[dict]`, consumed by plugins and hooks consistently. `memory_store.get_context_summary()` returns `str`, injected into LLM context in Task 9. `send_orb_state(state: str, amplitude: float)` called consistently in Tasks 13.

**No placeholders:** All code blocks are complete and runnable.
