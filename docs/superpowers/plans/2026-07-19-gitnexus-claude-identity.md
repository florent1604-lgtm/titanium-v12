# GitNexus Claude Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Faire reconnaître Claude comme client GitNexus local nommé et strictement read-only, sans facturation API Anthropic séparée, avec repli Ollama fail-closed.

**Architecture:** Claude Code conserve un unique endpoint MCP HTTP utilisateur vers `127.0.0.1:4747/api/mcp`; le doublon stdio projet est supprimé. Un petit module Python produit une attestation publique filtrée de l'authentification Claude (`SUBSCRIPTION_OK`, `API_BILLING_RISK` ou `UNVERIFIED`), que l'API services expose sans prétendre qu'une session MCP est permanente. Le manifeste indexé déclare l'identité et la frontière read-only; Ollama devient le fournisseur sélectionné dès que la garde Claude n'est plus sûre.

**Tech Stack:** Python 3.11+, pytest 9, FastAPI/aiohttp existants, PowerShell 5.1, Claude Code CLI 2.1.211, GitNexus 1.6.10-rc.50, JSON, Ollama `qwen2.5:7b`.

## Global Constraints

- C1 reste `advisory-read-only`; aucune capacité GitNexus native `rename` ou `group_sync` n'est attribuée à Claude.
- Aucun secret, email, identifiant d'organisation ou jeton Claude n'est écrit dans le dépôt, le bus ou les logs.
- L'endpoint Claude est exactement `http://127.0.0.1:4747/api/mcp`; aucun endpoint hors loopback.
- Claude est sélectionné uniquement si `authMethod=claude.ai`, `apiProvider=firstParty`, abonnement `pro|max`, aucune clé/jeton API et aucun fournisseur Bedrock/Vertex/Foundry.
- Tout état différent sélectionne `ollama:qwen2.5:7b` et reste visible.
- Une attestation est fraîche pendant exactement 86 400 secondes.
- PAPER ONLY sur le compte réel; aucun fichier de logique trading n'est modifié.
- Avant toute modification de symbole, exécuter GitNexus `impact(..., direction="upstream")`; avant chaque commit, exécuter `detect_changes(scope="staged")`.

---

## File Structure

- Create `tools/claude_gitnexus_identity.py`: évaluation pure de facturation, filtrage, persistance atomique et commande d'attestation.
- Create `tests/test_claude_gitnexus_identity.py`: contrats de sécurité et de fraîcheur du module.
- Modify `architecture/gitnexus/services.json`: identité Claude et frontière GitNexus read-only.
- Modify `tests/test_gitnexus_integration.py`: contrat structurel du manifeste.
- Modify `.mcp.json`: supprimer uniquement le transport GitNexus projet conflictuel; conserver le garde signé.
- Modify `tools/configure_gitnexus_mcp.ps1`: configurer Claude en HTTP utilisateur, Codex en direct et Hermes derrière son garde.
- Modify `tests/test_gitnexus_mcp_config.py`: unicité de l'endpoint et absence de secret.
- Modify `api/services_routes.py`: enveloppe RC `value`, statut Claude filtré et cycle GitNexus gracieux.
- Create `tests/test_services_gitnexus_clients.py`: réponses API et cycle start/stop.
- Modify `collab/LOG.md` and `collab/REVIEWS.md`: preuve de livraison et résultat de revue.

---

### Task 1: Garde de facturation et attestation Claude

**Files:**
- Create: `tools/claude_gitnexus_identity.py`
- Create: `tests/test_claude_gitnexus_identity.py`

**Interfaces:**
- Produces: `assess_billing(auth: Mapping[str, object], env: Mapping[str, str]) -> str`
- Produces: `build_public_attestation(auth, env, *, mcp_verified, verified_at) -> dict[str, object]`
- Produces: `write_attestation(payload: Mapping[str, object], path: Path = STATUS_PATH) -> None`
- Produces: `read_attestation(path: Path = STATUS_PATH, *, now: datetime | None = None) -> dict[str, object]`
- Produces CLI: `python tools/claude_gitnexus_identity.py attest --claude-exe <path> --mcp-verified`

- [ ] **Step 1: Write the failing unit tests**

Create `tests/test_claude_gitnexus_identity.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from tools.claude_gitnexus_identity import (
    build_public_attestation,
    read_attestation,
    write_attestation,
)


SAFE_AUTH = {
    "loggedIn": True,
    "authMethod": "claude.ai",
    "apiProvider": "firstParty",
    "subscriptionType": "pro",
    "email": "must-not-persist@example.invalid",
    "orgId": "must-not-persist",
    "orgName": "must-not-persist",
}


def test_subscription_auth_is_safe_and_filters_identity_data():
    when = datetime(2026, 7, 19, 17, 0, tzinfo=timezone.utc)
    result = build_public_attestation(
        SAFE_AUTH, {}, mcp_verified=True, verified_at=when,
    )
    assert result == {
        "identity": "claude",
        "configured": True,
        "verified_at": "2026-07-19T17:00:00+00:00",
        "verification_fresh": True,
        "transport": "http",
        "endpoint_scope": "loopback",
        "access": "advisory-read-only",
        "billing_guard": "SUBSCRIPTION_OK",
        "selected_provider": "claude",
        "fallback": "ollama:qwen2.5:7b",
    }
    serialized = json.dumps(result)
    assert "must-not-persist" not in serialized
    assert "email" not in serialized
    assert "org" not in serialized.lower()


def test_api_key_forces_ollama_fallback():
    result = build_public_attestation(
        SAFE_AUTH,
        {"ANTHROPIC_API_KEY": "present-but-never-copied"},
        mcp_verified=True,
        verified_at=datetime.now(timezone.utc),
    )
    assert result["billing_guard"] == "API_BILLING_RISK"
    assert result["selected_provider"] == "ollama"
    assert "present-but-never-copied" not in json.dumps(result)


def test_console_or_third_party_auth_forces_ollama():
    for auth in (
        {**SAFE_AUTH, "authMethod": "console"},
        {**SAFE_AUTH, "apiProvider": "bedrock"},
    ):
        result = build_public_attestation(
            auth, {}, mcp_verified=True,
            verified_at=datetime.now(timezone.utc),
        )
        assert result["billing_guard"] == "API_BILLING_RISK"
        assert result["selected_provider"] == "ollama"


def test_unverified_or_disconnected_auth_forces_ollama():
    result = build_public_attestation(
        {}, {}, mcp_verified=False,
        verified_at=datetime.now(timezone.utc),
    )
    assert result["configured"] is False
    assert result["billing_guard"] == "UNVERIFIED"
    assert result["selected_provider"] == "ollama"


def test_read_attestation_fails_closed_when_stale(tmp_path):
    path = tmp_path / "claude-status.json"
    when = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    payload = build_public_attestation(
        SAFE_AUTH, {}, mcp_verified=True, verified_at=when,
    )
    write_attestation(payload, path)

    result = read_attestation(
        path, now=when + timedelta(seconds=86_401),
    )
    assert result["verification_fresh"] is False
    assert result["billing_guard"] == "UNVERIFIED"
    assert result["selected_provider"] == "ollama"


def test_write_attestation_is_atomic_and_public(tmp_path):
    path = tmp_path / "claude-status.json"
    payload = build_public_attestation(
        SAFE_AUTH, {}, mcp_verified=True,
        verified_at=datetime.now(timezone.utc),
    )
    write_attestation(payload, path)
    assert json.loads(path.read_text(encoding="utf-8")) == payload
    assert not path.with_suffix(".tmp").exists()
```

- [ ] **Step 2: Run the tests and verify the expected import failure**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_claude_gitnexus_identity.py -q
```

Expected: collection fails with `ModuleNotFoundError: tools.claude_gitnexus_identity`.

- [ ] **Step 3: Implement the focused identity module**

Create `tools/claude_gitnexus_identity.py`:

```python
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from tools.gitnexus_runtime import RUNTIME_ROOT


STATUS_PATH = RUNTIME_ROOT / "claude-gitnexus-status.json"
ENDPOINT = "http://127.0.0.1:4747/api/mcp"
MAX_AGE_SECONDS = 86_400
RISK_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() not in {"", "0", "false", "no", "none"}


def assess_billing(
    auth: Mapping[str, object], env: Mapping[str, str],
) -> str:
    if any(_truthy(env.get(key)) for key in RISK_ENV_KEYS):
        return "API_BILLING_RISK"
    if not auth or auth.get("loggedIn") is not True:
        return "UNVERIFIED"
    if (
        auth.get("authMethod") == "claude.ai"
        and auth.get("apiProvider") == "firstParty"
        and str(auth.get("subscriptionType", "")).lower() in {"pro", "max"}
    ):
        return "SUBSCRIPTION_OK"
    return "API_BILLING_RISK"


def build_public_attestation(
    auth: Mapping[str, object],
    env: Mapping[str, str],
    *,
    mcp_verified: bool,
    verified_at: datetime,
) -> dict[str, object]:
    guard = assess_billing(auth, env) if mcp_verified else "UNVERIFIED"
    return {
        "identity": "claude",
        "configured": bool(mcp_verified),
        "verified_at": verified_at.astimezone(timezone.utc).isoformat(),
        "verification_fresh": True,
        "transport": "http",
        "endpoint_scope": "loopback",
        "access": "advisory-read-only",
        "billing_guard": guard,
        "selected_provider": "claude" if guard == "SUBSCRIPTION_OK" else "ollama",
        "fallback": "ollama:qwen2.5:7b",
    }


def _default_status() -> dict[str, object]:
    return build_public_attestation(
        {}, {}, mcp_verified=False, verified_at=datetime.now(timezone.utc),
    )


def write_attestation(
    payload: Mapping[str, object], path: Path = STATUS_PATH,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(path)


def read_attestation(
    path: Path = STATUS_PATH, *, now: datetime | None = None,
) -> dict[str, object]:
    current = now or datetime.now(timezone.utc)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        verified_at = datetime.fromisoformat(str(payload["verified_at"]))
        if verified_at.tzinfo is None:
            raise ValueError("verified_at must be timezone-aware")
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return _default_status()
    age = (current.astimezone(timezone.utc) - verified_at.astimezone(timezone.utc)).total_seconds()
    if age < 0 or age > MAX_AGE_SECONDS:
        payload.update({
            "verification_fresh": False,
            "billing_guard": "UNVERIFIED",
            "selected_provider": "ollama",
        })
    return payload


def attest_current(claude_exe: Path, *, mcp_verified: bool) -> dict[str, object]:
    result = subprocess.run(
        [str(claude_exe), "auth", "status"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        auth = json.loads(result.stdout) if result.returncode == 0 else {}
    except json.JSONDecodeError:
        auth = {}
    payload = build_public_attestation(
        auth,
        {key: os.environ.get(key, "") for key in RISK_ENV_KEYS},
        mcp_verified=mcp_verified,
        verified_at=datetime.now(timezone.utc),
    )
    write_attestation(payload)
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    attest = sub.add_parser("attest")
    attest.add_argument("--claude-exe", type=Path, required=True)
    attest.add_argument("--mcp-verified", action="store_true")
    args = parser.parse_args(argv)
    payload = attest_current(args.claude_exe, mcp_verified=args.mcp_verified)
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["billing_guard"] == "SUBSCRIPTION_OK" else 78


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the focused tests**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_claude_gitnexus_identity.py -q
```

Expected: `6 passed`.

- [ ] **Step 5: Check scope and commit Task 1**

Stage only the two Task 1 files, run GitNexus `detect_changes(scope="staged", repo="titanium-v12")`, and review every affected process. Expected risk: LOW because the module is new and not yet consumed.

```powershell
git add tools/claude_gitnexus_identity.py tests/test_claude_gitnexus_identity.py
git commit -m "feat: add Claude subscription billing guard"
```

---

### Task 2: Déclarer Claude dans la carte GitNexus

**Files:**
- Modify: `architecture/gitnexus/services.json`
- Modify: `tests/test_gitnexus_integration.py:23-32`

**Interfaces:**
- Consumes: endpoint et états définis par Task 1.
- Produces: `manifest["gitnexus"]["clients"]["claude"]` et frontière `gitnexus -> claude`.

- [ ] **Step 1: Strengthen the manifest contract test**

Extend `test_topology_manifest_is_local_paper_only_and_contains_all_participants` with:

```python
    claude = manifest["gitnexus"]["clients"]["claude"]
    assert claude == {
        "identity": "claude",
        "transport": "http",
        "endpoint": "http://127.0.0.1:4747/api/mcp",
        "access": "advisory-read-only",
        "billing_guard": "subscription-only",
        "fallback": "ollama:qwen2.5:7b",
    }
    assert {
        "from": "gitnexus",
        "to": "claude",
        "data": "code-map",
        "mode": "advisory-read-only",
    } in manifest["boundaries"]
    assert "rename" not in json.dumps(claude).lower()
    assert "group_sync" not in json.dumps(claude).lower()
```

- [ ] **Step 2: Run the test and verify the missing `clients` failure**

```powershell
venv\Scripts\python.exe -m pytest tests\test_gitnexus_integration.py::test_topology_manifest_is_local_paper_only_and_contains_all_participants -q
```

Expected: FAIL with `KeyError: 'clients'`.

- [ ] **Step 3: Add the exact client and boundary**

Inside the existing `gitnexus` object in `architecture/gitnexus/services.json`, add:

```json
"clients": {
  "claude": {
    "identity": "claude",
    "transport": "http",
    "endpoint": "http://127.0.0.1:4747/api/mcp",
    "access": "advisory-read-only",
    "billing_guard": "subscription-only",
    "fallback": "ollama:qwen2.5:7b"
  }
}
```

Append this object to `boundaries`:

```json
{"from": "gitnexus", "to": "claude", "data": "code-map", "mode": "advisory-read-only"}
```

- [ ] **Step 4: Run the manifest test**

```powershell
venv\Scripts\python.exe -m pytest tests\test_gitnexus_integration.py::test_topology_manifest_is_local_paper_only_and_contains_all_participants -q
```

Expected: PASS.

- [ ] **Step 5: Check scope and commit Task 2**

Stage the two files and run GitNexus `detect_changes(scope="staged")`. Expected: LOW, documentation/config only.

```powershell
git add architecture/gitnexus/services.json tests/test_gitnexus_integration.py
git commit -m "feat: register Claude as read-only GitNexus client"
```

---

### Task 3: Unifier l'endpoint MCP Claude et produire l'attestation

**Files:**
- Modify: `.mcp.json`
- Modify: `tools/configure_gitnexus_mcp.ps1`
- Modify: `tests/test_gitnexus_mcp_config.py:11-48`

**Interfaces:**
- Consumes: CLI Task 1 `attest --claude-exe ... --mcp-verified`.
- Produces: exactement un serveur utilisateur Claude nommé `gitnexus` sur l'endpoint HTTP canonique.
- Preserves: Codex direct via bootstrap et Hermes via `mcp_gitnexus_gate.py`.

- [ ] **Step 1: Replace the conflicting-config tests**

Replace the first three tests of `tests/test_gitnexus_mcp_config.py` with:

```python
def test_claude_project_scope_has_no_conflicting_gitnexus_transport():
    cfg = json.loads(Path(".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert "gitnexus" not in cfg
    assert cfg["gitnexus_write_gate"] == {
        "command": str(Path.cwd() / "gitnexus/gate-venv/Scripts/python.exe"),
        "args": [str(Path.cwd() / "mcp_gitnexus_gate.py")],
    }


def test_configurator_uses_claude_http_user_scope_without_credentials():
    script = Path("tools/configure_gitnexus_mcp.ps1").read_text(encoding="utf-8")
    endpoint = "http://127.0.0.1:4747/api/mcp"
    assert "$Claude" in script
    assert endpoint in script
    assert "mcp add --transport http --scope user gitnexus $ClaudeGitNexusEndpoint" in script
    assert "mcp remove gitnexus --scope user" in script
    assert "--mcp-verified" in script
    assert "ANTHROPIC_API_KEY" not in script
    assert "--header" not in script
    assert "--client-secret" not in script


def test_configurator_keeps_codex_direct_and_gates_hermes():
    script = Path("tools/configure_gitnexus_mcp.ps1").read_text(encoding="utf-8")
    assert "codex mcp add gitnexus -- node $GitNexusRuntime mcp" in script
    assert '"Y" | & $Hermes mcp add gitnexus --command $ProjectPython --args $GitNexusGate' in script
    assert "$HermesTest" in script
    assert 'notmatch "Connected"' in script
```

- [ ] **Step 2: Run the tests and confirm they fail against the stdio project entry**

```powershell
venv\Scripts\python.exe -m pytest tests\test_gitnexus_mcp_config.py -q
```

Expected: the new Claude project-scope and HTTP configurator assertions fail; unrelated gate tests pass.

- [ ] **Step 3: Remove only the project GitNexus entry**

Delete this object from `.mcp.json`:

```json
"gitnexus": {
  "command": "node",
  "args": ["C:\\Users\\flore\\Desktop\\v12\\tools\\gitnexus_mcp_bootstrap.mjs", "mcp"]
}
```

Keep `gitnexus_write_gate` unchanged. Validate the resulting JSON with:

```powershell
Get-Content -Raw .mcp.json | ConvertFrom-Json | Out-Null
```

- [ ] **Step 4: Add Claude discovery, endpoint repair, verification and attestation to the configurator**

After the existing path constants in `tools/configure_gitnexus_mcp.ps1`, add:

```powershell
$ClaudeGitNexusEndpoint = "http://127.0.0.1:4747/api/mcp"
$Claude = Get-ChildItem -Path (
    Join-Path $env:USERPROFILE ".vscode\extensions\anthropic.claude-code-*-win32-x64\resources\native-binary\claude.exe"
) -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 -ExpandProperty FullName
$IdentityTool = Join-Path $ProjectRoot "tools\claude_gitnexus_identity.py"
```

Add fail-closed prerequisites:

```powershell
if (-not $Claude -or -not (Test-Path -LiteralPath $Claude -PathType Leaf)) {
    throw "Claude Code CLI introuvable"
}
if (-not (Test-Path -LiteralPath $IdentityTool -PathType Leaf)) {
    throw "Garde identite Claude introuvable: $IdentityTool"
}
```

Before the existing Codex block, add the canonical Claude configuration:

```powershell
$ClaudeServers = (& $Claude mcp list 2>&1 | Out-String)
if ($ClaudeServers -match "(?m)^gitnexus:") {
    & $Claude mcp remove gitnexus --scope user | Out-Null
}
& $Claude mcp add --transport http --scope user gitnexus $ClaudeGitNexusEndpoint
if ($LASTEXITCODE -ne 0) { throw "Echec ajout MCP GitNexus a Claude" }

$ClaudeAfter = (& $Claude mcp list 2>&1 | Out-String)
if ($ClaudeAfter -match "Conflicting scopes") {
    throw "Conflit de scopes GitNexus Claude encore present"
}
if ($ClaudeAfter -notmatch [regex]::Escape("gitnexus: $ClaudeGitNexusEndpoint")) {
    throw "Endpoint GitNexus Claude absent ou incorrect"
}
if ($ClaudeAfter -notmatch "gitnexus:.*Connected") {
    throw "Handshake GitNexus/Claude non connecte"
}

& $ProjectPython $IdentityTool attest --claude-exe $Claude --mcp-verified
if ($LASTEXITCODE -ne 0) {
    throw "Claude n'est pas en mode abonnement sur: repli Ollama requis"
}
```

Update the final output to state separately that Claude is HTTP/read-only, Codex direct, and Hermes gated.

- [ ] **Step 5: Run the configuration tests**

```powershell
venv\Scripts\python.exe -m pytest tests\test_gitnexus_mcp_config.py tests\test_claude_gitnexus_identity.py -q
```

Expected: all tests PASS.

- [ ] **Step 6: Check scope and commit Task 3**

Stage only `.mcp.json`, the configurator and its test. Run GitNexus `detect_changes(scope="staged")`; review any config-file findings.

```powershell
git add .mcp.json tools/configure_gitnexus_mcp.ps1 tests/test_gitnexus_mcp_config.py
git commit -m "fix: unify Claude GitNexus MCP endpoint"
```

---

### Task 4: Exposer le client Claude et réutiliser le cycle GitNexus gracieux

**Files:**
- Modify: `api/services_routes.py:17-18,73-93,98-157,234-279`
- Create: `tests/test_services_gitnexus_clients.py`

**Interfaces:**
- Consumes: `read_attestation()` from Task 1.
- Consumes: `start_gitnexus_server()` and `stop_gitnexus_server()` from `tools.gitnexus_runtime`.
- Produces: `GET /services/status -> gitnexus.clients.claude`.

- [ ] **Step 1: Re-run required GitNexus impacts before editing**

Run these MCP calls against the fresh index:

```text
impact(target="services_status", file_path="api/services_routes.py", direction="upstream", includeTests=true)
impact(target="_gitnexus_repositories", file_path="api/services_routes.py", direction="upstream", includeTests=true)
impact(target="gitnexus_start", file_path="api/services_routes.py", direction="upstream", includeTests=true)
impact(target="gitnexus_stop", file_path="api/services_routes.py", direction="upstream", includeTests=true)
```

Baseline du 2026-07-19 : tous LOW; `_gitnexus_repositories` possède un appelant direct (`services_status`). Stop and warn Florent if the refreshed result becomes HIGH or CRITICAL.

- [ ] **Step 2: Write failing route and lifecycle tests**

Create `tests/test_services_gitnexus_clients.py`:

```python
from __future__ import annotations

import json

import pytest

from api import services_routes as routes


@pytest.mark.asyncio
async def test_services_status_exposes_public_claude_attestation(monkeypatch):
    async def gitnexus_ok():
        return True, 4747

    async def repositories():
        return [{"name": "titanium-v12", "stats": {"nodes": 24_354}}]

    async def ollama_off():
        return False

    attestation = {
        "identity": "claude",
        "configured": True,
        "verified_at": "2026-07-19T17:00:00+00:00",
        "verification_fresh": True,
        "transport": "http",
        "endpoint_scope": "loopback",
        "access": "advisory-read-only",
        "billing_guard": "SUBSCRIPTION_OK",
        "selected_provider": "claude",
        "fallback": "ollama:qwen2.5:7b",
    }
    monkeypatch.setattr(routes, "_gitnexus_responding", gitnexus_ok)
    monkeypatch.setattr(routes, "_gitnexus_repositories", repositories)
    monkeypatch.setattr(routes, "_ollama_responding", ollama_off)
    monkeypatch.setattr(routes, "read_claude_attestation", lambda: attestation)

    response = await routes.services_status()
    payload = json.loads(response.body)
    assert payload["gitnexus"]["clients"]["claude"] == attestation
    assert "connected" not in payload["gitnexus"]["clients"]["claude"]
    assert payload["gitnexus"]["symbols"] == 24_354


@pytest.mark.asyncio
async def test_gitnexus_repositories_accepts_rc_value(monkeypatch):
    class Response:
        status = 200
        async def json(self):
            return {"value": [{"name": "titanium-v12"}]}
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            return False

    class Session:
        def get(self, *_args, **_kwargs):
            return Response()
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(routes.aiohttp, "ClientSession", Session)
    assert await routes._gitnexus_repositories() == [{"name": "titanium-v12"}]


@pytest.mark.asyncio
async def test_gitnexus_start_uses_managed_runtime(monkeypatch):
    state = {"healthy": False}

    async def responding():
        return state["healthy"], 4747 if state["healthy"] else 0

    class Process:
        pid = 4242

    def start():
        state["healthy"] = True
        return Process()

    monkeypatch.setattr(routes, "_gitnexus_responding", responding)
    monkeypatch.setattr(routes, "start_gitnexus_server", start)
    response = await routes.gitnexus_start()
    assert json.loads(response.body)["status"] == "started"


@pytest.mark.asyncio
async def test_gitnexus_stop_uses_authenticated_graceful_runtime(monkeypatch):
    monkeypatch.setattr(routes, "stop_gitnexus_server", lambda: True)
    response = await routes.gitnexus_stop()
    assert json.loads(response.body)["status"] == "stopped"
```

- [ ] **Step 3: Run the tests and verify contract failures**

```powershell
venv\Scripts\python.exe -m pytest tests\test_services_gitnexus_clients.py -q
```

Expected: failures for missing `read_claude_attestation`, missing RC `value` handling and raw route lifecycle.

- [ ] **Step 4: Update imports and RC repository envelope**

Replace the GitNexus runtime import with:

```python
from tools.claude_gitnexus_identity import read_attestation as read_claude_attestation
from tools.gitnexus_runtime import (
    GITNEXUS_BASE_URL,
    start_gitnexus_server,
    stop_gitnexus_server,
)
```

Change the dict extraction in `_gitnexus_repositories` to:

```python
        repos = payload.get(
            "repos", payload.get("repositories", payload.get("value", []))
        )
```

- [ ] **Step 5: Publish Claude under the GitNexus service without a false live claim**

Change `gitnexus_info` to:

```python
    gitnexus_info = {
        "running": gn_ok,
        "port": gn_port,
        "symbols": gn_symbols,
        "repos": gn_repos,
        "url": "/nexus",
        "proc": _proc_running("gitnexus"),
        "clients": {"claude": read_claude_attestation()},
    }
```

- [ ] **Step 6: Replace raw GitNexus start/stop with the managed runtime**

Replace `gitnexus_start` with:

```python
@router.post("/gitnexus/start", dependencies=_ADMIN)
async def gitnexus_start():
    """Démarre l'instance GitNexus gérée et authentifiable du projet."""
    if (await _gitnexus_responding())[0]:
        return JSONResponse({"status": "already_running", "message": "GitNexus deja actif"})
    process = await asyncio.to_thread(start_gitnexus_server)
    for _ in range(20):
        await asyncio.sleep(0.5)
        ok, port = await _gitnexus_responding()
        if ok:
            if process is not None:
                _procs["gitnexus"] = process
            pid = getattr(process, "pid", None)
            return JSONResponse({
                "status": "started",
                "message": f"GitNexus demarre sur port {port}",
                "pid": pid,
            })
    return JSONResponse(
        {"status": "error", "message": "GitNexus non sain apres demarrage"},
        status_code=503,
    )
```

Replace `gitnexus_stop` with:

```python
@router.post("/gitnexus/stop", dependencies=_ADMIN)
async def gitnexus_stop():
    """Arrête uniquement l'instance enregistrée, via shutdown authentifié."""
    stopped = await asyncio.to_thread(stop_gitnexus_server)
    if not stopped:
        return JSONResponse(
            {"status": "not_managed", "message": "Aucune instance geree arretee"},
            status_code=409,
        )
    _procs["gitnexus"] = None
    return JSONResponse({"status": "stopped", "message": "GitNexus arrete proprement"})
```

- [ ] **Step 7: Run focused and adjacent tests**

```powershell
venv\Scripts\python.exe -m pytest tests\test_services_gitnexus_clients.py tests\test_gitnexus_runtime.py tests\test_gitnexus_integration.py -q
```

Expected: all tests PASS. The exact count is recorded from the run, not predicted.

- [ ] **Step 8: Check scope and commit Task 4**

Stage only the route and test. Run GitNexus `detect_changes(scope="staged")`. Baseline impact is LOW; stop and obtain Florent's confirmation if detect_changes reports HIGH or CRITICAL.

```powershell
git add api/services_routes.py tests/test_services_gitnexus_clients.py
git commit -m "fix: expose Claude and manage GitNexus lifecycle safely"
```

---

### Task 5: Appliquer, revalider et publier la reconnaissance Claude

**Files:**
- Modify: `collab/LOG.md`
- Modify: `collab/REVIEWS.md`

**Interfaces:**
- Consumes: all Task 1-4 deliverables.
- Produces: configuration Claude utilisateur vérifiée, attestation publique fraîche, index GitNexus frais et preuve de collaboration.

- [ ] **Step 1: Run the full targeted suite**

```powershell
venv\Scripts\python.exe -m pytest `
  tests\test_claude_gitnexus_identity.py `
  tests\test_gitnexus_mcp_config.py `
  tests\test_gitnexus_integration.py `
  tests\test_services_gitnexus_clients.py `
  tests\test_gitnexus_runtime.py -q
```

Expected: all tests PASS with no failure. Existing unrelated pytest configuration warnings may be reported separately.

- [ ] **Step 2: Apply the idempotent MCP configurator**

```powershell
powershell -ExecutionPolicy Bypass -File tools\configure_gitnexus_mcp.ps1
```

Expected output contains three independent confirmations: Claude HTTP/read-only, Codex direct, Hermes gated. The command must fail if Claude is not `SUBSCRIPTION_OK`.

- [ ] **Step 3: Verify the public attestation contains no personal data**

```powershell
$status = Get-Content -Raw "$env:LOCALAPPDATA\Titanium\gitnexus\claude-gitnexus-status.json" | ConvertFrom-Json
$status | Select-Object identity,configured,verified_at,verification_fresh,transport,endpoint_scope,access,billing_guard,selected_provider,fallback | ConvertTo-Json
```

Expected: `billing_guard=SUBSCRIPTION_OK`, `selected_provider=claude`, no email/org/key fields.

- [ ] **Step 4: Verify Claude sees one connected GitNexus endpoint**

```powershell
$Claude = Get-ChildItem -Path "$env:USERPROFILE\.vscode\extensions\anthropic.claude-code-*-win32-x64\resources\native-binary\claude.exe" -File |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
& $Claude mcp list
```

Expected: one line `gitnexus: http://127.0.0.1:4747/api/mcp ... Connected`, and no `Conflicting scopes` diagnostic.

- [ ] **Step 5: Validate the live read-only API**

```powershell
$status = Invoke-RestMethod http://127.0.0.1:8090/services/status -TimeoutSec 5
$status.gitnexus.clients.claude | ConvertTo-Json
```

Expected: the same public attestation, without a `connected` field.

- [ ] **Step 6: Exercise the GitNexus graceful lifecycle and graph**

Use the admin-protected dashboard route only with the existing local admin mechanism; never print the token. After stop/start, run:

```powershell
Invoke-RestMethod http://127.0.0.1:4747/api/health -TimeoutSec 10
$body = @{repo="titanium-v12"; cypher="MATCH (n:File) RETURN COUNT(n) AS count"} | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:4747/api/query -Method Post -ContentType application/json -Body $body -TimeoutSec 60
```

Expected: health `ok`, query HTTP 200 and a positive file count. Also execute one BM25 query through the MCP client and confirm success.

- [ ] **Step 7: Reindex and prove Claude is discoverable**

```powershell
venv\Scripts\python.exe tools\gitnexus_runtime.py session --no-watch
```

Then query GitNexus for `Claude identity advisory-read-only billing guard`. Expected: the identity specification and manifest appear in definitions/results.

- [ ] **Step 8: Record delivery and request Claude review**

Append a concise entry to both collaboration files containing:

```markdown
## 2026-07-19 - Claude reconnu par GitNexus

- Endpoint MCP unique : `http://127.0.0.1:4747/api/mcp`.
- Garde : `SUBSCRIPTION_OK`; aucune clé API ni donnée personnelle persistée.
- Accès : `advisory-read-only`; repli `ollama:qwen2.5:7b`.
- Tests, cycle stop/start, Cypher, BM25 et reindexation : résultats exacts du run.
- PAPER ONLY ; aucun chemin trading ou CommandGateway activé.
```

Send the same evidence through `node tools/collab_bus.mjs send` to Claude and Hermes, asking for `GO` or `REQUEST CHANGES`.

- [ ] **Step 9: Final detect_changes and documentation commit**

Stage only `collab/LOG.md` and `collab/REVIEWS.md`, run GitNexus `detect_changes(scope="staged")`, then:

```powershell
git add collab/LOG.md collab/REVIEWS.md
git commit -m "docs: record Claude GitNexus recognition"
```

- [ ] **Step 10: Final verification before completion**

```powershell
git diff --check
git status --short
venv\Scripts\python.exe tools\gitnexus_runtime.py status --json
```

Expected: no whitespace error in Task files, GitNexus healthy, watcher state reported, and no uncommitted Task file. Do not clean or alter unrelated user/Claude changes.

