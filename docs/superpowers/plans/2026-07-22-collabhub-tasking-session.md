# CollabHub Tasking and Session Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter au journal CollabHub les tâches, échecs, relances manuelles et sessions locales Florent nécessaires au Command Deck.

**Architecture:** Les messages existants restent immuables. Des tables et contrats spécialisés portent l'état projeté des tâches ; chaque transition écrit d'abord un événement durable. Une session locale courte autorise les écritures `florent`, sans donner de capacité système.

**Tech Stack:** Python 3.12, dataclasses/Pydantic, Starlette, SQLite WAL/FULL, pytest.

## Global Constraints

- Conserver les cinq outils MCP exacts ; aucune action Windows ou trading ajoutée au MCP.
- Validation et secret gate avant toute persistance.
- Relance manuelle uniquement ; chaque tentative reçoit un nouvel identifiant.
- Migration SQLite additive et idempotente.

---

### Task 1: Secret gate et session locale

**Files:**
- Create: `collab_hub/secret_gate.py`
- Create: `collab_hub/session.py`
- Create: `collab_hub/windows_attestation.py`
- Test: `tests/test_collab_hub_session.py`

**Interfaces:**
- Produces: `scan_text(value: str) -> tuple[str, ...]`, `WindowsAttestation.challenge()`, `WindowsAttestation.verify(sid, nonce, proof)`, `SessionAuthority.issue(windows_sid: str) -> LocalSession`, `SessionAuthority.verify(token: str) -> LocalSession`.

- [ ] **Step 1: Écrire les tests rouges**

```python
def test_secret_gate_rejects_bearer_and_private_key():
    assert scan_text("Authorization: Bearer abcdefghijklmnop") == ("BEARER_TOKEN",)
    assert scan_text("-----BEGIN PRIVATE KEY-----") == ("PRIVATE_KEY",)

def test_session_expires_and_never_serializes_token(fake_clock):
    authority = SessionAuthority(clock=fake_clock, ttl_seconds=900)
    issued = authority.issue("S-1-5-21-test")
    assert authority.verify(issued.token).windows_sid == "S-1-5-21-test"
    assert "token" not in authority.audit_view(issued)
    fake_clock.advance(901)
    with pytest.raises(SessionExpired):
        authority.verify(issued.token)

def test_windows_proof_is_bound_to_sid_and_single_use(attestation):
    nonce = attestation.challenge()
    proof = attestation.test_proof("S-1-5-21-florent", nonce)
    attestation.verify("S-1-5-21-florent", nonce, proof)
    with pytest.raises(ReplayRejected):
        attestation.verify("S-1-5-21-florent", nonce, proof)
```

- [ ] **Step 2: Lancer le test et constater l'échec**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_collab_hub_session.py -q`
Expected: FAIL import modules.

- [ ] **Step 3: Implémenter la version minimale**

```python
@dataclass(frozen=True)
class LocalSession:
    session_id: str
    windows_sid: str
    expires_at: datetime
    token: str = field(repr=False)

class SessionAuthority:
    def issue(self, windows_sid: str) -> LocalSession: ...
    def verify(self, token: str) -> LocalSession: ...
```

Use `secrets.token_urlsafe(32)`, compare with `hmac.compare_digest`, store only
`sha256(token)` in memory, and return fixed reason codes from the secret gate.
La preuve Windows est un HMAC-SHA256 sur `sid|nonce|expires_at`. La clé bootstrap
32 octets est protégée par DPAPI CurrentUser dans
`%LOCALAPPDATA%\Titanium\CommandDeck\session.key.dpapi`, avec ACL utilisateur +
SYSTEM seulement. Injecter une interface de protection en test ; aucun fallback
en clair. Le nonce expire après 30 s et n'est consommable qu'une fois.

- [ ] **Step 4: Vérifier le vert**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_collab_hub_session.py -q`
Expected: PASS.

- [ ] **Step 5: Commit ciblé**

```powershell
git add collab_hub/secret_gate.py collab_hub/session.py tests/test_collab_hub_session.py
node .gitnexus/run.cjs detect-changes -s staged -r titanium-v12
git commit -m "feat(collab): add bounded local sessions and secret gate"
```

### Task 2: Contrats et stockage des tâches

**Files:**
- Create: `collab_hub/task_contracts.py`
- Create: `collab_hub/task_store.py`
- Modify: `collab_hub/store.py`
- Test: `tests/test_collab_hub_tasks.py`

**Interfaces:**
- Produces: `TaskDraft`, `TaskRecord`, `AttemptFailure`, `TaskStore.create_task`, `transition`, `record_failure`, `request_retry`, `list_failed`, et `CollabStore.read_before(before_offset, limit)` pour l'historique paginé.

- [ ] **Step 1: Impact GitNexus obligatoire**

Run: `node .gitnexus/run.cjs impact CollabStore -r titanium-v12 -d upstream`
Expected now: exact context with ten importing modules; stop and warn on HIGH/CRITICAL.

- [ ] **Step 2: Écrire les tests rouges de transition**

```python
def test_failure_is_immutable_and_retry_creates_new_attempt(store):
    task = store.create_task(TaskDraft(title="Reindex", owner="codex", priority="P1"))
    failure = store.record_failure(task.task_id, "TEST_FAILED", "pytest:1")
    retry = store.request_retry(task.task_id, requested_by="florent")
    assert retry.attempt_id != failure.attempt_id
    assert store.list_failed(statuses=("NOUVEAU",))[0].reason_code == "TEST_FAILED"
```

- [ ] **Step 3: Lancer le test rouge**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_collab_hub_tasks.py -q`
Expected: FAIL missing task store.

- [ ] **Step 4: Implémenter schéma et machine d'état**

Créer `task_events`, `tasks` et `task_attempts` avec `event_id` unique,
`created_at`, `payload_sha256` et transitions exactes : `NOUVEAU`, `A_ANALYSER`,
`CORRECTIF_EN_COURS`, `A_REVALIDER`, `CLOS`. Refuser toute transition non listée
et toute raison hors registre. `CollabStore` possède une instance `TaskStore`
partageant la même connexion et la ferme dans le même cycle de vie.
`read_before` utilise `global_offset < ? ORDER BY global_offset DESC LIMIT ?` puis
retourne la page dans l'ordre croissant ; aucune migration destructive.

- [ ] **Step 5: Vérifier migration et concurrence**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_collab_hub_store.py tests/test_collab_hub_tasks.py -q`
Expected: PASS, WAL conservé.

- [ ] **Step 6: Commit ciblé**

```powershell
git add collab_hub/task_contracts.py collab_hub/task_store.py collab_hub/store.py tests/test_collab_hub_tasks.py
node .gitnexus/run.cjs detect-changes -s staged -r titanium-v12
git commit -m "feat(collab): add durable task and failure ledger"
```

### Task 3: Routes session, tâches et recherche

**Files:**
- Create: `collab_hub/task_routes.py`
- Create: `collab_hub/session_routes.py`
- Modify: `collab_hub/app.py`
- Test: `tests/test_collab_hub_task_api.py`

**Interfaces:**
- Produces: `POST /v1/session/challenge`, `POST /v1/session/windows`, `GET /v1/messages?before_offset=`, `GET/POST /v1/tasks`, `POST /v1/tasks/{id}/transition`, `POST /v1/tasks/{id}/retry`, `GET /v1/failures`.

- [ ] **Step 1: Impact `create_app`**

Run: `node .gitnexus/run.cjs impact create_app -r titanium-v12 -d upstream`
Expected: three direct callers; warn if risk changes from LOW.

- [ ] **Step 2: Écrire les tests HTTP rouges**

```python
def test_retry_requires_florent_session_and_is_manual(client, token):
    denied = client.post("/v1/tasks/t1/retry")
    assert denied.status_code == 401
    accepted = client.post("/v1/tasks/t1/retry", headers={"X-Collab-Session": token})
    assert accepted.status_code == 201
    assert accepted.json()["requested_by"] == "florent"
```

Ajouter les cas : SID sans preuve, nonce expiré, nonce rejoué et HMAC altéré
retournent tous 401 avec un reason code fixe, sans fuite de comparaison.
Tester aussi que `before_offset` et `after_offset` sont mutuellement exclusifs et
que deux pages antérieures reconstruisent l'ordre global sans trou ni doublon.

- [ ] **Step 3: Lancer rouge puis implémenter les route factories**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_collab_hub_task_api.py -q`
Expected before implementation: FAIL route 404. Après implémentation : PASS.

- [ ] **Step 4: Vérifier absence de retry automatique**

Avancer une horloge factice de 24 h après un échec et affirmer que le nombre de
tentatives reste inchangé.

- [ ] **Step 5: Commit ciblé**

```powershell
git add collab_hub/task_routes.py collab_hub/session_routes.py collab_hub/app.py tests/test_collab_hub_task_api.py
node .gitnexus/run.cjs detect-changes -s staged -r titanium-v12
git commit -m "feat(collab): expose authenticated task workflow"
```

### Task 4: Gate Florent et non-régression MCP

**Files:**
- Modify: `collab_hub/app.py`
- Modify: `collab_hub/contracts.py`
- Test: `tests/test_collab_hub_florent_gate.py`
- Test: `tests/test_collab_hub_mcp.py`

**Interfaces:**
- Produces: publication `principal=florent` refusée sans session ; autres agents continuent via MCP C1.

- [ ] **Step 1: Écrire le test rouge d'usurpation**

```python
def test_http_cannot_impersonate_florent(client):
    payload = valid_message(principal="florent")
    assert client.post("/v1/messages", json=payload).status_code == 401
```

- [ ] **Step 2: Implémenter `require_florent_session` avant secret gate/persist**

La route HTTP vérifie la session si `principal == "florent"`, puis exécute
`scan_text` avant de construire `MessageDraft`.

- [ ] **Step 3: Vérifier la surface exacte**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_collab_hub_*.py -q`
Expected: PASS et liste MCP exacte `collab_publish/read/ack/presence/health`.

- [ ] **Step 4: Commit ciblé**

```powershell
git add collab_hub/app.py collab_hub/contracts.py tests/test_collab_hub_florent_gate.py tests/test_collab_hub_mcp.py
node .gitnexus/run.cjs detect-changes -s staged -r titanium-v12
git commit -m "fix(collab): attest Florent writes and preserve C1 MCP"
```
