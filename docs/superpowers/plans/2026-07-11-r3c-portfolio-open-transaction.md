# R3c Portfolio Open Transaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Garantir que toute ouverture paper crypto, forex ou swing passe par le garde R3 dans une transaction commune avant mutation d'état.

**Architecture:** `core.portfolio_risk.opening_transaction()` expose un verrou réentrant process-local. Les trois moteurs prennent ce verrou, appellent `check_can_open`, puis inscrivent la position sans `await` avant de libérer la transaction. Le moteur crypto calcule d'abord sa taille finale, applique le garde central, puis seulement débite le cash et insère la position.

**Tech Stack:** Python 3.12, `threading.RLock`, `contextlib.contextmanager`, asyncio, pytest.

## Global Constraints

- PAPER ONLY ; aucun ordre réel et aucun chemin live.
- Aucun commit, push ou merge sans validation explicite de Florent.
- `check_can_open` reste fail-closed sur données ou état invalides.
- Aucun `await` ne doit apparaître à l'intérieur de `opening_transaction()`.
- Le runtime de test est `C:\Users\flore\Desktop\v12\venv\Scripts\python.exe` hors sandbox.

---

### Task 1: Transaction commune swing/forex

**Files:**
- Modify: `core/portfolio_risk.py`
- Modify: `core/swing_engine.py`
- Modify: `core/forex_engine.py`
- Test: `tests/test_portfolio_risk.py`

**Interfaces:**
- Consumes: `check_can_open(strategy, symbol, notional_eur, equity, side) -> tuple[bool, str]`
- Produces: `opening_transaction() -> ContextManager[None]`

- [ ] **Step 1: écrire le test rouge de sérialisation inter-moteurs**

Ajouter les imports `threading`, `time` et `ThreadPoolExecutor`, puis :

```python
def test_open_transaction_serializes_swing_and_forex(monkeypatch):
    import core.swing_engine as se
    import core.forex_engine as fe

    monkeypatch.setitem(se.swing_state, "positions", {})
    monkeypatch.setitem(se.swing_state, "equity", 10_000.0)
    monkeypatch.setitem(fe.forex_state, "positions", {})
    monkeypatch.setitem(fe.forex_state, "equity", 10_000.0)

    start = threading.Barrier(3)
    counter_lock = threading.Lock()
    active = 0
    max_active = 0

    def slow_guard(*args):
        nonlocal active, max_active
        with counter_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.08)
        with counter_lock:
            active -= 1
        return True, "ok"

    monkeypatch.setattr(pr, "check_can_open", slow_guard)

    def open_swing():
        start.wait()
        return se._open_position(
            "SWING_TEST", "long", 100.0, 1.0,
            {"sl_atr": 2.0, "tp_ladder": [1.0, 2.0, 3.0], "tf": "H4"},
        )

    def open_forex():
        start.wait()
        return fe._open_position("FOREX_TEST", "long", 1.10, 0.01)

    with ThreadPoolExecutor(max_workers=2) as pool:
        left = pool.submit(open_swing)
        right = pool.submit(open_forex)
        start.wait()
        assert left.result() and right.result()

    assert max_active == 1
```

- [ ] **Step 2: exécuter le test rouge**

Run:

```powershell
& 'C:\Users\flore\Desktop\v12\venv\Scripts\python.exe' -m pytest tests/test_portfolio_risk.py::test_open_transaction_serializes_swing_and_forex -q -p no:cacheprovider
```

Expected: `FAIL`, avec `max_active == 2` avant transaction commune.

- [ ] **Step 3: ajouter le verrou process-local**

Dans `core/portfolio_risk.py` :

```python
import threading
from contextlib import contextmanager
from typing import Iterator

_OPENING_LOCK = threading.RLock()


@contextmanager
def opening_transaction() -> Iterator[None]:
    """Sérialise check R3 + mutation d'ouverture dans ce process."""
    with _OPENING_LOCK:
        yield
```

- [ ] **Step 4: protéger les deux ouvertures MT5**

Dans chaque `_open_position`, importer les deux interfaces et envelopper le garde ainsi que l'insertion :

```python
from core.portfolio_risk import check_can_open, opening_transaction

with opening_transaction():
    ok, reason = check_can_open(strategy, sym, notional, state["equity"], side)
    if not ok:
        logger.info("... %s", reason)
        return False
    state["positions"][sym] = position_payload
return True
```

La construction pure du payload peut rester hors transaction ; aucun `await` n'est permis dans le bloc.

- [ ] **Step 5: exécuter le test vert et les régressions MT5**

Run:

```powershell
& 'C:\Users\flore\Desktop\v12\venv\Scripts\python.exe' -m pytest tests/test_portfolio_risk.py tests/test_bar_dedup.py -q -p no:cacheprovider
```

Expected: tous les tests passent, sans warning d'état persistant.

### Task 2: Appliquer R3 aux ouvertures crypto

**Files:**
- Modify: `execution/paper_trading.py`
- Test: `tests/test_paper_trading.py`

**Interfaces:**
- Consumes: `opening_transaction()` et `check_can_open("crypto", symbol, size_usdt, current_eq, side)`
- Produces: refus `None` sans débit cash ni position si R3 bloque.

- [ ] **Step 1: écrire le test rouge du garde crypto**

Dans `TestOpenPosition` :

```python
def test_portfolio_risk_guard_blocks_crypto_open(self, monkeypatch):
    import core.portfolio_risk as pr

    engine = _make_engine()
    before_cash = engine.cash
    calls = []

    def deny(strategy, symbol, notional, equity, side):
        calls.append((strategy, symbol, notional, equity, side))
        return False, "plafond net portefeuille atteint"

    monkeypatch.setattr(pr, "check_can_open", deny)
    position = run(engine.open_position(_signal()))

    assert position is None
    assert calls and calls[0][0] == "crypto"
    assert engine.cash == before_cash
    assert engine.positions == {}
```

- [ ] **Step 2: exécuter le test rouge**

Run:

```powershell
& 'C:\Users\flore\Desktop\v12\venv\Scripts\python.exe' -m pytest tests/test_paper_trading.py::TestOpenPosition::test_portfolio_risk_guard_blocks_crypto_open -q -p no:cacheprovider
```

Expected: `FAIL` car `check_can_open` n'est pas appelé.

- [ ] **Step 3: intégrer le garde après le sizing final et avant mutation**

Construire `PaperPosition` sans modifier le cash. Puis :

```python
from core.portfolio_risk import check_can_open, opening_transaction

with opening_transaction():
    ok, reason = check_can_open("crypto", sym, size_usdt, current_eq, side)
    if not ok:
        logger.info("[PAPER] %s NON ouvert — risque portefeuille: %s", sym, reason)
        return None
    self.cash -= total_cost
    self.positions[sym] = pos
    self._last_prices[sym] = price
    self._update_equity_curve()

await self._save_state_unsafe()
```

- [ ] **Step 4: exécuter le test vert puis la suite paper/R3**

Run:

```powershell
& 'C:\Users\flore\Desktop\v12\venv\Scripts\python.exe' -m pytest tests/test_paper_trading.py tests/test_portfolio_risk.py tests/test_bar_dedup.py tests/test_atomic_state.py -q -p no:cacheprovider
```

Expected: tous les tests passent.

### Task 3: Revue et handoff

**Files:**
- Modify: `collab/REVIEWS.md`
- Modify: `collab/LOG.md`
- Modify: `collab/TASKS.md`

**Interfaces:**
- Consumes: sorties pytest fraîches et diff limité R3c.
- Produces: message bus à Claude/Hermes avec fichiers, tests et risques résiduels.

- [ ] **Step 1:** vérifier `git diff -- core/portfolio_risk.py core/swing_engine.py core/forex_engine.py execution/paper_trading.py tests/test_portfolio_risk.py tests/test_paper_trading.py`.
- [ ] **Step 2:** exécuter les tests ciblés une dernière fois.
- [ ] **Step 3:** consigner les preuves dans `REVIEWS.md`, `LOG.md` et `TASKS.md`.
- [ ] **Step 4:** demander la revue croisée Claude via le bus, sans commit ni redémarrage automatique.

