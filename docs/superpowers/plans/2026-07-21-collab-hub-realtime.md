# CollabHub Realtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire un hub local durable et temps réel pour Claude, Codex, Hermès et Florent, strictement limité à la collaboration C1 shadow.

**Architecture:** Un package `collab_hub` isolé fournit contrats, store SQLite, diffusion et API FastAPI. Le même processus monte un serveur MCP, tandis que le bus NDJSON existant reste un fallback temporaire.

**Tech Stack:** Python 3.11+, SQLite/WAL, FastAPI 0.136, Starlette WebSocket/SSE, MCP 1.28.1, pytest.

## Global Constraints

- Écoute réseau exacte : `127.0.0.1:8770`.
- Store autoritaire : `data/collab_hub/collab-v1.sqlite3`.
- C1 shadow uniquement ; aucun ordre, shell, secret, permission ou écriture arbitraire.
- PAPER/DEMO only ; compte réel `60261188` interdit.
- TDD rouge/vert pour chaque comportement.
- Aucun fichier runtime trading n'est modifié.

---

### Task 1: Contrats et store durable

**Files:**
- Create: `collab_hub/__init__.py`
- Create: `collab_hub/contracts.py`
- Create: `collab_hub/store.py`
- Test: `tests/test_collab_hub_store.py`

**Interfaces:**
- Produces: `MessageDraft`, `StoredMessage`, `PublishReceipt`, `CollabStore.publish`, `read`, `ack`, `consumer_offset`, `set_presence`, `list_presence`, `health`.

- [ ] **Step 1: Write failing tests** for durable publish, exact retry, divergent retry, concurrent offsets, monotone ACK and restart persistence.
- [ ] **Step 2: Run** `.\venv\Scripts\python.exe -m pytest tests\test_collab_hub_store.py -q -p no:cacheprovider` and verify failures are missing-module/missing-behavior failures.
- [ ] **Step 3: Implement minimal contracts and SQLite store** with strict enums, canonical JSON, WAL/FULL and `BEGIN IMMEDIATE`.
- [ ] **Step 4: Run the same test file** and require zero failures.

### Task 2: HTTP API and realtime replay

**Files:**
- Create: `collab_hub/app.py`
- Test: `tests/test_collab_hub_api.py`

**Interfaces:**
- Consumes: `CollabStore` and contract dataclasses.
- Produces: `create_app(store: CollabStore) -> FastAPI` with `/health`, `/v1/messages`, `/v1/consumers/{id}/ack`, `/v1/presence`, `/v1/stream`, `/v1/ws`.

- [ ] **Step 1: Write failing TestClient tests** proving publish-after-commit, replay from offset, invalid payload rejection, SSE event IDs and WebSocket disconnect cleanup.
- [ ] **Step 2: Run** `.\venv\Scripts\python.exe -m pytest tests\test_collab_hub_api.py -q -p no:cacheprovider` and verify expected failures.
- [ ] **Step 3: Implement the minimal FastAPI routes** and a bounded broadcaster whose queue overflow disconnects only the slow client.
- [ ] **Step 4: Run store and API tests** and require zero failures.

### Task 3: MCP C1-only adapter

**Files:**
- Create: `collab_hub/mcp.py`
- Modify: `collab_hub/app.py`
- Test: `tests/test_collab_hub_mcp.py`

**Interfaces:**
- Consumes: one `CollabStore` instance shared with FastAPI.
- Produces: FastMCP tools `collab_publish`, `collab_read`, `collab_ack`, `collab_presence`, `collab_health`, mounted at `/mcp`.

- [ ] **Step 1: Write failing tests** asserting the exact five-tool allowlist and rejecting any forbidden tool name.
- [ ] **Step 2: Run** `.\venv\Scripts\python.exe -m pytest tests\test_collab_hub_mcp.py -q -p no:cacheprovider` and verify expected failures.
- [ ] **Step 3: Implement the five tools** as thin calls into `CollabStore`, with no filesystem, subprocess, Git, permission or trading imports.
- [ ] **Step 4: Run MCP, API and store tests** and require zero failures.

### Task 4: Singleton and client configuration

**Files:**
- Create: `tools/collab_hub_server.py`
- Modify: `tools/mcp_singletons.ps1`
- Modify: `.mcp.json`
- Modify: `.codex/config.toml`
- Test: `tests/test_collab_hub_config.py`

**Interfaces:**
- Produces: managed listener `collab-hub` on 8770 and MCP client entry `collab_hub` at `http://127.0.0.1:8770/mcp`.

- [ ] **Step 1: Write failing configuration tests** for exact URL, singleton script and absence of Base44.
- [ ] **Step 2: Run** `.\venv\Scripts\python.exe -m pytest tests\test_collab_hub_config.py -q -p no:cacheprovider` and verify expected failures.
- [ ] **Step 3: Add the launcher and configuration entries** without changing existing 4750/8091/8766 services.
- [ ] **Step 4: Run configuration and existing singleton/Hermès tests** and require zero failures.

### Task 5: NDJSON import and fallback

**Files:**
- Create: `collab_hub/import_ndjson.py`
- Create: `tools/collab_hub_import.py`
- Test: `tests/test_collab_hub_import.py`

**Interfaces:**
- Consumes: `collab/messages/stream.ndjson` and `acks.ndjson` read-only.
- Produces: idempotent import receipts; source files remain untouched.

- [ ] **Step 1: Write failing tests** for malformed-line reporting, stable re-import and no source mutation.
- [ ] **Step 2: Run** `.\venv\Scripts\python.exe -m pytest tests\test_collab_hub_import.py -q -p no:cacheprovider` and verify expected failures.
- [ ] **Step 3: Implement deterministic import** with `legacy:<id>` idempotency keys and an explicit error report.
- [ ] **Step 4: Run import and store tests** and require zero failures.

### Task 6: Service identity signing

**Files:**
- Create: `collab_hub/identity.py`
- Create: `collab/governance/collab_principals.json`
- Create: `tools/collab_identity_keygen.py`
- Test: `tests/test_collab_hub_identity.py`

**Interfaces:**
- Produces: canonical envelope signing/verifying and an opt-in `COLLAB_REQUIRE_SIGNATURES=1` gate.

- [ ] **Step 1: Write failing tests** for valid signature, wrong principal, tampered payload, nonce replay and expired timestamp.
- [ ] **Step 2: Run** `.\venv\Scripts\python.exe -m pytest tests\test_collab_hub_identity.py -q -p no:cacheprovider` and verify expected failures.
- [ ] **Step 3: Implement Ed25519 verification** using public keys only in the repository; key generation writes private material outside the repository.
- [ ] **Step 4: Run identity and full CollabHub tests** and require zero failures. Keep signature enforcement off until keys are provisioned and cross-review is complete.

### Task 7: Live proof and handoff

**Files:**
- Modify: `collab/HERMES_BRIDGE.md`
- Modify: `collab/LOG.md`
- Modify: `collab/REVIEWS.md`

**Interfaces:**
- Produces: verified health, MCP handshake, publish/read/ACK/replay proof and rollback instructions.

- [ ] **Step 1: Start the singleton** with `powershell -NoProfile -ExecutionPolicy Bypass -File tools\mcp_singletons.ps1 start`.
- [ ] **Step 2: Verify** HTTP health, MCP `initialize`/`tools/list`, one message from each principal and replay after reconnect.
- [ ] **Step 3: Run** `.\venv\Scripts\python.exe -m pytest tests\test_collab_hub_store.py tests\test_collab_hub_api.py tests\test_collab_hub_mcp.py tests\test_collab_hub_config.py tests\test_collab_hub_import.py tests\test_collab_hub_identity.py tests\test_hermes_bridge_config.py tests\test_mcp_singleton_supervisor.py -q -p no:cacheprovider`.
- [ ] **Step 4: Run GitNexus** `node .gitnexus/run.cjs detect-changes --scope compare --base-ref master --repo titanium-v12` and review every affected symbol/flow before any commit.
- [ ] **Step 5: Send Claude the evidence** on the legacy bus and request independent ACCEPT/REQUEST_CHANGES.

