# EventPlane C0a Read-Only Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Realign the dormant C0a mirror with the frozen EventPlane v1 registry, harden the canonical SQLite journal, and expose strictly read-only observability without changing any trading decision or execution path.

**Architecture:** SQLite WAL remains the canonical journal and replay authority. C0a only reads the existing confluence snapshot and appends registry-valid facts; an off-by-default observer loop and two bounded GET endpoints expose those facts. NATS JetStream relay, the complete F0 supervisor, Hermes named-pipe bridge, and C0b mirrors are separate follow-up plans so this first slice remains independently testable and reversible.

**Tech Stack:** Python 3.12, SQLite WAL, JSON Schema Draft 2020-12 via `jsonschema`, FastAPI, asyncio, pytest, GitNexus.

## Global Constraints

- PAPER ONLY on account `60261188`; DEMO account `50061786` remains behind its existing fail-closed wall.
- `CONFLUENCE_AGGRESSIVE_EXEC` and all trading flags are unchanged; aggressive information is mirrored as data only.
- Consensus remains detection-only with `decision_capability=false` and `orders_capability=false`; C0b is not part of this plan.
- No EventPlane event can call an executor, clear a kill switch, mutate a motor, or traverse a command gateway.
- `docs/contracts/eventplane-v1-registry.json` version `eventplane-registry/1.0.0`, status `FROZEN`, compatibility `CLOSED_EXACT`, is normative.
- Registry SHA-256 must remain `6CE8BC5DAC6B79C6339CF20BA38D28C9D454A9914CFAB55491BFDFB8A72E8BEA`.
- SQLite `global_offset` is strictly increasing and unique but may be sparse; only `stream_seq` plus the per-stream hash chain is contiguous.
- Every runtime symbol edit requires GitNexus upstream impact first; HIGH or CRITICAL results stop the task for an explicit warning and review.
- Every task uses TDD, an isolated commit, `git diff --check`, targeted tests, and staged `detect_changes` before commit.
- No `.env`, token, password, account credential, API key, or raw secret value is logged, persisted, committed, or copied into a failure record.

---

## File Map

- `core/event_registry.py`: frozen-registry loader, SHA verification, exact payload validation, and secret pre-persistence gate.
- `core/event_plane.py`: canonical SQLite append/read/integrity implementation; delegates contract checks to `event_registry`.
- `core/event_mirror.py`: C0a adapter from `confluence_demo_engine.status_snapshot()` to registry-valid facts.
- `core/event_observer.py`: cancellable, observation-only periodic runner around `mirror_once`.
- `api/eventplane_routes.py`: bounded GET-only health and event-read API.
- `api/api_server.py`: router inclusion and one gated observation task; no engine or executor modification.
- `utils/config.py`: off-by-default observer settings only.
- `.env.example`: non-secret documentation for the observer flags.
- `requirements.txt` and `requirements-test.txt`: JSON Schema validator dependency.
- `tests/test_event_registry.py`: digest, closed-registry, payload, and secret-gate tests.
- `tests/test_event_plane.py`: crash/concurrency/sparse-offset/integrity tests.
- `tests/test_event_mirror.py`: exact C0a and heartbeat contract tests.
- `tests/test_event_observer.py`: cadence, cancellation, and failure-visibility tests.
- `tests/test_eventplane_routes.py`: response bounding, redaction, and GET-only contract tests.
- `docs/runbooks/EVENTPLANE_READONLY.md`: enable, verify, degrade, and rollback procedure.

### Task 1: Runtime Registry Gate

**Files:**
- Create: `core/event_registry.py`
- Create: `tests/test_event_registry.py`
- Modify: `requirements.txt`
- Modify: `requirements-test.txt`

**Interfaces:**
- Consumes: `docs/contracts/eventplane-v1-registry.json` and its `.sha256` companion.
- Produces: `RegistryViolation`, `RegistryDigestMismatch`, `SecretDetected`, `load_registry() -> dict`, `validate_payload(event_type: str, payload: Mapping[str, Any]) -> None`, and `assert_secret_free(value: Any) -> None`.

- [ ] **Step 1: Check impacts before dependency and module edits**

Run:
```text
GitNexus impact target=requirements.txt direction=upstream repo=titanium-v12
GitNexus impact target=requirements-test.txt direction=upstream repo=titanium-v12
```
Expected: no trading process affected. If risk is HIGH/CRITICAL, stop and publish the blast radius.

- [ ] **Step 2: Write failing registry tests**

Create tests that assert the frozen digest, reject an unknown event type, reject an additional payload property, accept the exact C0a payload below, and reject nested keys `api_key`, `authorization`, `password`, `private_key`, `secret`, `token`, and `x_admin_token` without including their values in the exception:

```python
VALID_C0A = {
    "decision_id": "d-btc-1",
    "as_of": "2026-07-19T07:30:00+00:00",
    "state_version": "confluence/1.1.0",
    "result": "BLOCK",
    "side": "short",
    "reason_codes": ["BLOCK_PILLAR_MISSING"],
    "data_valid": True,
    "setup_family": "reversal",
    "rank": 2.0,
    "n_pillars": 2,
    "aggressive_eligible": False,
    "decision_capability": False,
    "orders_capability": False,
}

def test_exact_c0a_payload_is_valid():
    validate_payload("confluence.evaluation.completed.v1", VALID_C0A)

def test_closed_registry_rejects_extra_property():
    with pytest.raises(RegistryViolation, match="additionalProperties"):
        validate_payload(
            "confluence.evaluation.completed.v1",
            {**VALID_C0A, "verdict": "BLOCK"},
        )

def test_secret_value_never_appears_in_error():
    leaked = "sk-live-never-print-this"
    with pytest.raises(SecretDetected) as caught:
        assert_secret_free({"nested": {"api_key": leaked}})
    assert leaked not in str(caught.value)
```

- [ ] **Step 3: Run tests and verify RED**

Run: `.\.pyembed\python.exe -m pytest tests/test_event_registry.py -q`

Expected: FAIL because `core.event_registry` does not exist.

- [ ] **Step 4: Add the validator dependency**

Append `jsonschema>=4.23.0,<5.0.0` once to both requirement files. Do not install or add NATS in this task.

- [ ] **Step 5: Implement the minimal frozen-registry gate**

Implement the public functions with these rules:

```python
REGISTRY_PATH = ROOT / "docs" / "contracts" / "eventplane-v1-registry.json"
DIGEST_PATH = ROOT / "docs" / "contracts" / "eventplane-v1-registry.sha256"

@lru_cache(maxsize=1)
def load_registry() -> dict:
    raw = REGISTRY_PATH.read_bytes()
    expected = DIGEST_PATH.read_text(encoding="ascii").split()[0].lower()
    actual = hashlib.sha256(raw).hexdigest()
    if not secrets.compare_digest(actual, expected):
        raise RegistryDigestMismatch("REGISTRY_DIGEST_MISMATCH")
    registry = json.loads(raw)
    if registry.get("status") != "FROZEN" or registry.get("compatibility") != "CLOSED_EXACT":
        raise RegistryViolation("REGISTRY_NOT_FROZEN")
    return registry

def validate_payload(event_type: str, payload: Mapping[str, Any]) -> None:
    registry = load_registry()
    definition = registry["types"].get(event_type)
    if definition is None:
        raise RegistryViolation("UNKNOWN_EVENT_TYPE")
    assert_secret_free(payload)
    schema = {
        "$schema": registry["$schema"],
        "$defs": registry["$defs"],
        **definition["payload_schema"],
    }
    errors = sorted(Draft202012Validator(schema).iter_errors(dict(payload)), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.path) or "$"
        raise RegistryViolation(f"PAYLOAD_SCHEMA_VIOLATION:{path}:{first.validator}")
```

`assert_secret_free` must recursively walk mappings and sequences, compare normalized key names against the denylist, scan strings for obvious bearer/private-key/API-key patterns, and raise only `SECRET_DETECTED:<path>`; it must never interpolate a value.

- [ ] **Step 6: Run registry tests and verify GREEN**

Run: `.\.pyembed\python.exe -m pytest tests/test_event_registry.py -q`

Expected: all tests PASS after the dependency is installed in the active Titanium environment.

- [ ] **Step 7: Commit the isolated gate**

Run `git diff --check`, stage only the four files in this task, run GitNexus `detect_changes(scope="staged")`, then commit:

```text
feat: enforce frozen EventPlane registry
```

### Task 2: Canonical SQLite Journal Hardening

**Files:**
- Modify: `core/event_plane.py`
- Modify: `tests/test_event_plane.py`

**Interfaces:**
- Consumes: `validate_payload()` and `assert_secret_free()` from Task 1.
- Produces: the existing `EventPlane.publish/read/ack/verify_integrity/health` API plus `EventPlane.close() -> None`; no executor-facing interface.

- [ ] **Step 1: Run mandatory symbol impacts**

Run upstream impact for `EventPlane.publish`, `EventPlane._validate`, `EventPlane.verify_integrity`, `EventPlane.health`, and `get_event_plane` with `file_path=core/event_plane.py`. Report direct callers, affected processes, and risk before editing. Stop on HIGH/CRITICAL.

- [ ] **Step 2: Write failing hardening tests**

Add tests with these exact assertions:

```python
def test_unknown_type_and_secret_are_rejected_before_insert(tmp_path):
    plane = _plane(tmp_path)
    with pytest.raises(ep.SchemaViolation, match="UNKNOWN_EVENT_TYPE"):
        plane.publish(_draft(etype="unknown.fact.v1"))
    with pytest.raises(ep.SchemaViolation, match="SECRET_DETECTED"):
        plane.publish(_draft(payload={"api_key": "never-store"}))
    assert plane.health()["n_events"] == 0

def test_global_offset_gap_is_not_integrity_failure(tmp_path):
    plane = _plane(tmp_path)
    plane.publish(_draft("first", payload=VALID_C0A))
    with pytest.raises(ep.IdempotencyConflict):
        plane.publish(_draft("first", payload={**VALID_C0A, "rank": 3.0}))
    plane.publish(_draft("second", payload={**VALID_C0A, "decision_id": "d2"}))
    assert plane.verify_integrity()["ok"] is True

def test_concurrent_publish_has_unique_stream_seq(tmp_path):
    plane = _plane(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(lambda n: plane.publish(
            _draft(f"k{n}", payload={**VALID_C0A, "decision_id": f"d{n}"})
        ), range(32)))
    assert sorted(r.stream_seq for r in receipts) == list(range(1, 33))
```

Also test `close()` and reopening the same database preserves events and integrity.

- [ ] **Step 3: Run tests and verify RED**

Run: `.\.pyembed\python.exe -m pytest tests/test_event_plane.py -q`

Expected: FAIL on registry enforcement and `close()`.

- [ ] **Step 4: Implement minimal hardening**

In `_validate`, call `validate_payload(d.event_type, d.payload)` after basic envelope checks and translate `RegistryViolation` to `SchemaViolation` using only the sanitized exception text. Keep `BEGIN IMMEDIATE`, WAL, `synchronous=FULL`, and per-process `RLock`. Add:

```python
def close(self) -> None:
    with self._lock:
        self._cx.close()
```

Do not require contiguous `global_offset`; `read()` remains `WHERE global_offset > ? ORDER BY global_offset ASC`. Keep integrity continuity on `stream_seq` and `prev_event_hash` only. Extend `health()` with registry version/digest, journal mode, and `transport_mode="SQLITE_FALLBACK"`; do not claim JetStream health.

- [ ] **Step 5: Run targeted and adjacent tests**

Run:
```text
.\.pyembed\python.exe -m pytest tests/test_event_plane.py tests/test_event_registry.py tests/test_cortex.py -q
```

Expected: PASS, with no import of `execution.*` from `core/event_plane.py`.

- [ ] **Step 6: Commit the isolated journal hardening**

Run `git diff --check`, stage only `core/event_plane.py` and `tests/test_event_plane.py`, run staged `detect_changes`, review all affected flows, then commit:

```text
fix: harden canonical EventPlane journal
```

### Task 3: Realign C0a Confluence Mirror

**Files:**
- Modify: `core/event_mirror.py`
- Modify: `tests/test_event_mirror.py`

**Interfaces:**
- Consumes: `core.confluence_demo_engine.status_snapshot()`, `EventDraft`, and `EventPlane.publish()`.
- Produces: unchanged `mirror_once(*, plane=None, status_fn=None, instance_id="runtime", now=None) -> dict` with registry-valid C0a facts and task heartbeat.

- [ ] **Step 1: Run mandatory symbol impacts**

Run upstream impact for `mirror_once`, `_parse_ts`, and `_n_pillars` in `core/event_mirror.py`. Current expected baseline is LOW with no trading process; if the fresh result differs, publish it before editing.

- [ ] **Step 2: Replace prototype expectations with exact contract tests**

Tests must assert no `verdict`, `code`, `symbol`, or `aggressive_ready` key exists in the payload. The BTC fact must equal:

```python
{
    "decision_id": "d-btc-1",
    "as_of": "2026-07-19T07:30:00+00:00",
    "state_version": "confluence/1.1.0",
    "result": "BLOCK",
    "side": "short",
    "reason_codes": ["BLOCK_PILLAR_MISSING"],
    "data_valid": True,
    "setup_family": "reversal",
    "rank": 2.0,
    "n_pillars": 2,
    "aggressive_eligible": False,
    "decision_capability": False,
    "orders_capability": False,
}
```

The heartbeat type must be `runtime.task.heartbeat.v1`, never `runtime.mirror.heartbeat.v1`, and contain exactly `task_id`, `owner`, `observed_at`, `state`, `heartbeat_age_seconds`, `criticality`, and `restart_capability`.

- [ ] **Step 3: Run mirror tests and verify RED**

Run: `.\.pyembed\python.exe -m pytest tests/test_event_mirror.py -q`

Expected: FAIL on the prototype field names and unregistered heartbeat type.

- [ ] **Step 4: Implement exact mapping without motor mutation**

Map numeric/string side to `long|short|neutral`; normalize `setup_family` to `continuation|reversal|None`; use `code` as the single reason code or `CONFLUENCE_REASON_UNAVAILABLE`; copy `data_valid`; coerce `rank` to finite float; compute `n_pillars`; map only `(aggressive or {}).ready` to `aggressive_eligible`. Always set both capabilities to `False`.

Use `partition_key=f"instrument:{sym}"` and `scope.instrument_id=sym`; instrument identity stays in the envelope, not in the exact payload. Skip `ERROR` snapshots. Use second-resolution heartbeat idempotency. On failure, store only `type(exc).__name__` and the fixed detail `PUBLISH_FAILED_REDACTED`; never `repr(exc)`.

- [ ] **Step 5: Run C0a, journal, confluence, and demo-wall tests**

Run:
```text
.\.pyembed\python.exe -m pytest tests/test_event_mirror.py tests/test_event_plane.py tests/test_confluence_demo_engine.py tests/test_demo_bridge.py -q
```

Expected: PASS; no new order or decision call originates from `event_mirror`.

- [ ] **Step 6: Claude/Codex two-stage review and commit**

Claude implements or reviews the exact registry mapping; Codex independently verifies schema fields, secret handling, and call graph. Stage only the two C0a files, run `detect_changes(scope="staged")`, then commit:

```text
fix: align C0a mirror with frozen registry
```

### Task 4: Off-by-Default Observation Runner

**Files:**
- Create: `core/event_observer.py`
- Create: `tests/test_event_observer.py`
- Modify: `utils/config.py`
- Modify: `.env.example`
- Modify: `api/api_server.py`

**Interfaces:**
- Consumes: `mirror_once()` from Task 3.
- Produces: `run_observer(*, stop_event: asyncio.Event, interval_seconds: float, mirror_fn=mirror_once) -> None`; config `EVENTPLANE_OBSERVER_ENABLED=False` and `EVENTPLANE_OBSERVER_SECONDS=5`.

- [ ] **Step 1: Run mandatory impacts and warn on runtime risk**

Run upstream impact for `lifespan` in `api/api_server.py`, `_bool` and `_int` in `utils/config.py`, and the new runner’s intended import boundary. The lifespan is a critical fan-in: any HIGH/CRITICAL result must be shown to Florent before editing and reviewed by Claude.

- [ ] **Step 2: Write failing runner tests**

Use an injected async-safe counter and `asyncio.Event` to prove one immediate call, repeated cadence, clean cancellation, and continued operation after a mirror exception. Assert the runner never imports `execution.demo_bridge`, `execution.order_executor`, or any MT5 placement function.

```python
@pytest.mark.asyncio
async def test_observer_runs_and_stops_without_trading_side_effects():
    calls = 0
    stop = asyncio.Event()
    def mirror():
        nonlocal calls
        calls += 1
        if calls == 2:
            stop.set()
        return {"n_published": 0, "n_duplicates": 0, "n_errors": 0}
    await asyncio.wait_for(
        run_observer(stop_event=stop, interval_seconds=0.01, mirror_fn=mirror),
        timeout=1,
    )
    assert calls == 2
```

- [ ] **Step 3: Run runner tests and verify RED**

Run: `.\.pyembed\python.exe -m pytest tests/test_event_observer.py -q`

Expected: FAIL because `core.event_observer` does not exist.

- [ ] **Step 4: Implement runner and gated lifespan hook**

The loop calls `await asyncio.to_thread(mirror_fn)`, catches and logs only the exception class, then waits with `asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)`. In lifespan, create the task only when `EVENTPLANE_OBSERVER_ENABLED` is true, name it `eventplane_observer`, and set the stop event during shutdown before task cancellation. Do not touch the confluence, consensus, aggressive, demo bridge, executor, or risk-manager branches.

- [ ] **Step 5: Verify default-off behavior**

Document only:

```dotenv
EVENTPLANE_OBSERVER_ENABLED=0
EVENTPLANE_OBSERVER_SECONDS=5
```

Run API import/lifespan tests with the flag absent and assert no EventPlane database is created. Run again with an injected temporary DB and flag enabled; assert facts are appended but no execution mock is called.

- [ ] **Step 6: Commit the isolated runner**

Run targeted tests, `git diff --check`, staged `detect_changes`, and Claude review of the lifespan hunk. Commit only the five task files:

```text
feat: add gated read-only EventPlane observer
```

### Task 5: Bounded Read-Only API

**Files:**
- Create: `api/eventplane_routes.py`
- Create: `tests/test_eventplane_routes.py`
- Modify: `api/api_server.py`

**Interfaces:**
- Consumes: `get_event_plane().health()` and `get_event_plane().read()`.
- Produces: `GET /eventplane/health` and `GET /eventplane/read?after_offset=0&limit=100&event_type=...`; no POST/PUT/PATCH/DELETE route.

- [ ] **Step 1: Run route impact analysis**

Run GitNexus `api_impact` for the new paths and upstream impact for the router-inclusion section in `api/api_server.py`. Confirm there is no route collision and no mutation consumer.

- [ ] **Step 2: Write failing API tests**

Test these invariants:

```python
def test_eventplane_routes_are_get_only(app):
    methods = {
        method
        for route in app.routes
        if getattr(route, "path", "").startswith("/eventplane/")
        for method in getattr(route, "methods", set())
    }
    assert methods == {"GET"}

def test_read_is_bounded_and_redacts_account_reference(client, seeded_plane):
    response = client.get("/eventplane/read?after_offset=0&limit=5000")
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 200
    assert all("account_ref" not in event["scope"] for event in body["events"])
```

Also assert negative offsets return 422, unknown event types return 422, payloads are returned only for registered non-sensitive types, and health never exposes a filesystem path or credential.

- [ ] **Step 3: Run API tests and verify RED**

Run: `.\.pyembed\python.exe -m pytest tests/test_eventplane_routes.py -q`

Expected: FAIL because the router does not exist.

- [ ] **Step 4: Implement the two GET endpoints**

Use `Query(ge=0)` for `after_offset`, `Query(ge=1, le=200)` for `limit`, and validate each optional `event_type` against the frozen registry. Serialize only event identity, timestamps, stream/sequence, source component, safe scope `{operating_mode,instrument_id,venue}`, classification, payload, and hashes. Never return `account_ref`, database path, consumer failure detail, or a raw exception.

Health must return `status`, `registry_version`, `registry_sha256`, `transport_mode`, `n_events`, `last_offset`, `consumer_failures`, and integrity state. `UNKNOWN`, digest mismatch, or integrity failure is never rendered healthy.

- [ ] **Step 5: Include router and run API regression**

Add one import and one `app.include_router(eventplane_router)` beside the other read-only routers. Run:

```text
.\.pyembed\python.exe -m pytest tests/test_eventplane_routes.py tests/test_cortex.py tests/test_titanium_snapshot.py -q
```

Expected: PASS; OpenAPI contains only the two EventPlane GET operations.

- [ ] **Step 6: Commit the isolated API**

Run `git diff --check`, staged `detect_changes`, route-map/shape checks, and commit only the three task files:

```text
feat: expose bounded EventPlane observability
```

### Task 6: Read-Only Production Gate and Rollback

**Files:**
- Create: `docs/runbooks/EVENTPLANE_READONLY.md`
- Modify: no trading or execution source file.

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: a verified operator procedure; no new runtime API.

- [ ] **Step 1: Write the runbook with exact enable/disable commands**

Document preflight, enabling only `EVENTPLANE_OBSERVER_ENABLED=1`, expected `SQLITE_FALLBACK` state until the NATS plan lands, health/read curl or PowerShell commands, log signatures, database backup location, and immediate rollback by restoring `EVENTPLANE_OBSERVER_ENABLED=0` plus Titanium restart. State that rollback does not delete the append-only journal.

- [ ] **Step 2: Run the complete non-trading regression**

Run:
```text
.\.pyembed\python.exe -m pytest tests/test_event_registry.py tests/test_event_plane.py tests/test_event_mirror.py tests/test_event_observer.py tests/test_eventplane_routes.py tests/test_cortex.py tests/test_consensus_engine.py tests/test_confluence_demo_engine.py tests/test_demo_bridge.py -q
```

Expected: PASS with aggressive execution configuration unchanged and consensus still reporting both capabilities false.

- [ ] **Step 3: Perform static safety assertions**

Run:
```text
rg -n "place_demo|send_order|order_send|CommandGateway|clear.*kill" core/event_registry.py core/event_plane.py core/event_mirror.py core/event_observer.py api/eventplane_routes.py
```

Expected: no match. Run a secret scan on the exact staged files and confirm no `.env` is staged.

- [ ] **Step 4: Perform final GitNexus and Claude review**

Run `detect_changes(scope="compare", base_ref="master")` from the implementation branch, inspect every affected process, and ask Claude for GO/REQUEST CHANGES on: registry exactness, no secret persistence, no Event-to-order path, lifespan cancellation, GET-only API, and rollback. Any HIGH/CRITICAL unexpected flow blocks activation.

- [ ] **Step 5: Activate observation-only canary**

After GO from one available supervisor (Claude or Codex), enable only the observer flag for a 30-minute canary. Verify: heartbeat age, event growth, idempotent duplicates, zero integrity break, zero order-count delta attributable to EventPlane, no consensus capability change, and no aggressive flag change.

- [ ] **Step 6: Record outcome and commit the runbook**

Write observed timestamps/counts and reviewer decision to `collab/REVIEWS.md` and the collaboration bus without secrets. Stage the runbook and allowed collaboration records only, run staged `detect_changes`, then commit:

```text
docs: add EventPlane read-only operations runbook
```

## Deferred Plans

- NATS JetStream relay, durable consumers, event-id/digest reconciliation, and return-from-fallback protocol.
- Full F0 supervisor with leases, epochs, restart budgets, and singleton detection.
- Hermes Windows service identity plus SID-restricted named-pipe read bridge.
- C0b mirrors for consensus, emotion, and lead/lag; all remain observation-only and require their own frozen payload review.
- Dashboard visualization of EventPlane and F0 health after the GET contracts are stable.

## Self-Review Result

- Spec coverage for the requested first slice: registry freeze, canonical SQLite authority, C0a, secret gate, sparse offsets, read-only wiring, tests, canary, and rollback are mapped to Tasks 1–6.
- Deliberately deferred scope is named explicitly and cannot be mistaken for completed NATS/F0/Hermes work.
- No placeholder instruction is used; every implementation task has concrete interfaces, commands, expected results, and commit boundaries.
- Type names and payload keys match `eventplane-registry/1.0.0`; `runtime.mirror.heartbeat.v1` never appears as an allowed output.
