# Hermes GitNexus Native Write Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose GitNexus `rename` and `group_sync` to Hermes only through a fail-closed, single-use approval gate supervised by Claude or Codex.

**Architecture:** Claude and Codex keep their direct GitNexus MCP connection. Hermes is moved from the direct GitNexus command to a local MCP proxy that forwards only tools explicitly annotated read-only and intercepts the two authorized destructive tools. A write is prepared from a real GitNexus preview and impact report, approved on the append-only collaboration bus, fingerprinted, executed once, then verified with `detect_changes` and supervisor-run tests.

**Tech Stack:** Dedicated Python 3.11 environment at `gitnexus/gate-venv`, Python MCP SDK (`mcp==1.28.1`), Node.js GitNexus 1.6.9 MCP server, NDJSON collaboration bus, pytest, Node test runner, PowerShell configuration.

## Global Constraints

- Repository root is exactly `C:\Users\flore\Desktop\v12`.
- Repository name is exactly `titanium-v12`.
- The only write tools are `rename` and `group_sync`.
- One prior approval from `claude` or `codex` is required and expires after 15 minutes.
- `HIGH`/`CRITICAL`, `core/`, `execution/`, `domain/`, `api/`, state-writing utilities, or trading-related changes also require an explicit `florent` approval for that request.
- No `.env`, secret, JARVIS path, commit, push, deletion, broker mutation, or real-account action is permitted.
- `rename` always performs a downstream `dry_run:true` preview before a request can exist.
- `group_sync` refuses unless `group_list` proves the group exists and every member resolves to the V12 root. There are currently no GitNexus groups, so the tool remains fail-closed after activation.
- Direct GitNexus writes must not remain reachable by Hermes after the proxy is installed.
- The broken project/JARVIS virtual environments must not be repaired or reused; the gate owns the ignored `gitnexus/gate-venv` environment.
- The proxy must refuse any present or future downstream tool whose `annotations.readOnlyHint` is not exactly `true`, except the explicitly gated `rename` and `group_sync` tools.
- The proxy never executes arbitrary shell commands or a caller-supplied test command. Post-write tests are a separate supervisor checkpoint using the fixed commands in this plan.
- Trust boundary: the gate prevents accidental or unapproved agent writes; it does not defend against a malicious process already running as Florent that can edit the local append-only bus. A supervisor approval must therefore originate from the active Claude or Codex session.
- No commit may be created unless Florent gives a separate explicit commit authorization at execution time.

---

## File Structure

- Create `tools/gitnexus_write_policy.py`: pure canonicalization, path checks, hashing, TTL, approval validation, replay ledger, sensitive-scope classification.
- Create `mcp_gitnexus_gate.py`: MCP proxy, downstream GitNexus client, read forwarding, two-phase `rename`/`group_sync`, post-write verification.
- Modify `tools/collab_bus.mjs`: add structured `approve-write` messages without changing existing send/ack contracts.
- Modify `tests/test_collab_bus.mjs`: cover structured approvals and rejected identities/verdicts.
- Create `tests/test_gitnexus_write_policy.py`: pure fail-closed policy tests.
- Create `tests/test_gitnexus_write_gate_mcp.py`: fake-downstream integration tests for preview, approval, execution, replay and verification.
- Create `requirements-gitnexus-gate.txt`: exact runtime/test pins for the isolated gate environment.
- Modify `tools/configure_gitnexus_mcp.ps1`: keep Codex direct, register the local proxy as Hermes's `gitnexus` server.
- Modify `.mcp.json`: add `gitnexus_write_gate` for reviewer inspection, while Claude's existing `gitnexus` remains direct.
- Modify `tests/test_gitnexus_mcp_config.py`: prove the split configuration and absence of secrets.
- Modify `collab/HERMES_BRIDGE.md`, `collab/governance/OPERATING_MODEL.md`, `collab/TASKS.md`, `collab/LOG.md`: operational contract, activation evidence and rollback instructions.

---

### Task 1: Structured supervisor approval on the append-only bus

**Files:**
- Modify: `tools/collab_bus.mjs`
- Modify: `tests/test_collab_bus.mjs`

**Interfaces:**
- Consumes: existing `args()`, `required()`, `append()` and `load()` helpers.
- Produces: `approve-write --from <claude|codex|florent> --for <request-id> --tool <rename|group_sync> --args-sha256 <64 hex> [--florent-override]`.
- Message contract: `{type:"gitnexus_write_approval", verdict:"APPROVED", tool, args_sha256, florent_override:boolean, in_reply_to, from, to:"hermes"}`.

- [ ] **Step 1: Write the failing Node tests**

Add these cases to `tests/test_collab_bus.mjs`:

```javascript
test("approve-write emits a strict structured approval", async () => {
  const dir = await mkdtemp(join(tmpdir(), "titanium-gate-"));
  const busFile = join(dir, "messages.jsonl");
  const requestId = "11111111-1111-4111-8111-111111111111";
  const digest = "a".repeat(64);
  const approval = run(busFile, "approve-write",
    "--from", "codex", "--for", requestId,
    "--tool", "rename", "--args-sha256", digest);
  assert.equal(approval.type, "gitnexus_write_approval");
  assert.equal(approval.verdict, "APPROVED");
  assert.equal(approval.in_reply_to, requestId);
  assert.equal(approval.to, "hermes");
  assert.equal(approval.args_sha256, digest);
  assert.equal(approval.florent_override, false);
});

test("approve-write rejects unknown supervisors and malformed hashes", async () => {
  const dir = await mkdtemp(join(tmpdir(), "titanium-gate-"));
  const busFile = join(dir, "messages.jsonl");
  assert.throws(() => run(busFile, "approve-write",
    "--from", "hermes", "--for", "req",
    "--tool", "rename", "--args-sha256", "bad"));
});
```

- [ ] **Step 2: Run the tests and verify red**

Run: `node --test tests/test_collab_bus.mjs`  
Expected: FAIL because `approve-write` falls through to `usage()`.

- [ ] **Step 3: Implement the strict command**

Insert before the existing `send/ack` branch in `tools/collab_bus.mjs`:

```javascript
const WRITE_SUPERVISORS = new Set(["claude", "codex", "florent"]);
const WRITE_TOOLS = new Set(["rename", "group_sync"]);

if (command === "approve-write") {
  required(values, ["from", "for", "tool", "args-sha256"]);
  const from = values.from.toLowerCase();
  if (!WRITE_SUPERVISORS.has(from)) throw new Error("Invalid write supervisor");
  if (!WRITE_TOOLS.has(values.tool)) throw new Error("Invalid GitNexus write tool");
  if (!/^[0-9a-f]{64}$/i.test(values["args-sha256"])) {
    throw new Error("Invalid --args-sha256");
  }
  const message = {
    id: randomUUID(), type: "gitnexus_write_approval", verdict: "APPROVED",
    from, to: "hermes", task: "GITNEXUS_WRITE",
    in_reply_to: values.for, ts_utc: new Date().toISOString(),
    tool: values.tool, args_sha256: values["args-sha256"].toLowerCase(),
    florent_override: from === "florent" && values["florent-override"] === true,
    content: "APPROVED", body: "APPROVED",
  };
  await append(defaultAck, message);
  console.log(JSON.stringify(message));
```

Change the following `if (command === "send" || command === "ack")` to `else if`.

- [ ] **Step 4: Run the Node tests and verify green**

Run: `node --test tests/test_collab_bus.mjs`  
Expected: all tests PASS.

- [ ] **Step 5: Reviewer checkpoint**

Review that the new branch only appends NDJSON and cannot execute GitNexus. Do not commit. If Florent separately authorizes a commit, use:

```powershell
git add tools/collab_bus.mjs tests/test_collab_bus.mjs
git commit -m "feat: add structured GitNexus write approvals"
```

---

### Task 2: Pure fail-closed write policy

**Files:**
- Create: `tools/gitnexus_write_policy.py`
- Create: `tests/test_gitnexus_write_policy.py`

**Interfaces:**
- Produces `WriteRequest`, `canonical_args()`, `args_sha256()`, `validate_repo_path()`, `fingerprint_files()`, `classify_sensitive()`, `find_valid_approvals()` and `ExecutionLedger.consume_once()`.
- Consumes approvals from `collab/messages/acks.ndjson` and file paths extracted from a downstream rename preview.

- [ ] **Step 1: Write failing policy tests**

Create `tests/test_gitnexus_write_policy.py` with fixtures rooted in `tmp_path` and these assertions:

```python
def test_only_native_tools_and_v12_repo_are_allowed(tmp_path):
    assert policy.normalize_args("rename", {"repo": "titanium-v12", "new_name": "x"})
    with pytest.raises(policy.GateRefused, match="TOOL_NOT_ALLOWED"):
        policy.normalize_args("cypher", {})
    with pytest.raises(policy.GateRefused, match="REPO_NOT_ALLOWED"):
        policy.normalize_args("rename", {"repo": "jarvis-runtime", "new_name": "x"})

def test_approval_is_single_use_exact_hash_and_fifteen_minutes(tmp_path):
    req = make_request(tmp_path, risk="LOW")
    approval = make_approval(req, actor="codex", age_seconds=899)
    assert policy.find_valid_approvals(req, [approval]).supervisor == "codex"
    with pytest.raises(policy.GateRefused, match="APPROVAL_EXPIRED"):
        policy.find_valid_approvals(req, [make_approval(req, actor="codex", age_seconds=901)])
    ledger = policy.ExecutionLedger(tmp_path / "executions.ndjson", tmp_path / "gate.lock")
    ledger.consume_once(req.request_id)
    with pytest.raises(policy.GateRefused, match="APPROVAL_REPLAY"):
        ledger.consume_once(req.request_id)

def test_sensitive_or_high_risk_requires_florent_and_supervisor(tmp_path):
    req = make_request(tmp_path, risk="HIGH", files=["api/swing_routes.py"])
    approvals = [make_approval(req, actor="claude")]
    with pytest.raises(policy.GateRefused, match="FLORENT_REQUIRED"):
        policy.find_valid_approvals(req, approvals)
    approvals.append(make_approval(req, actor="florent", florent_override=True))
    assert policy.find_valid_approvals(req, approvals).supervisor == "claude"
```

- [ ] **Step 2: Run the policy tests and verify red**

Run: `.\gitnexus\gate-venv\Scripts\python.exe -m pytest tests\test_gitnexus_write_policy.py -q -p no:cacheprovider`  
Expected: collection FAIL because `tools.gitnexus_write_policy` does not exist.

- [ ] **Step 3: Implement the policy module**

Use these exact public types and constants:

```python
ROOT = Path(r"C:\Users\flore\Desktop\v12").resolve()
ALLOWED_REPO = "titanium-v12"
ALLOWED_TOOLS = frozenset({"rename", "group_sync"})
SUPERVISORS = frozenset({"claude", "codex"})
TTL_SECONDS = 900
SENSITIVE_PREFIXES = ("core/", "execution/", "domain/", "api/")
SENSITIVE_FILES = frozenset({
    "utils/atomic_state.py",
    "tools/gitnexus_runtime.py",
    "tools/collab_bus.mjs",
})

class GateRefused(RuntimeError):
    pass

@dataclass(frozen=True)
class WriteRequest:
    request_id: str
    tool: Literal["rename", "group_sync"]
    args: dict[str, Any]
    args_sha256: str
    created_ts: datetime
    expires_ts: datetime
    impact_risk: str
    files: tuple[str, ...]
    file_fingerprint: str

@dataclass(frozen=True)
class ApprovalSet:
    supervisor: Literal["claude", "codex"]
    florent_override: bool
```

`normalize_args()` must force `repo="titanium-v12"`; for rename it must reject `dry_run:false` during preparation and require `new_name` plus one of `symbol_name`/`symbol_uid`; for group sync it must require a non-empty `name` and reject unknown keys. `validate_repo_path()` must use `Path.resolve()` and `Path.is_relative_to(ROOT)`. `args_sha256()` must hash UTF-8 JSON with `sort_keys=True` and separators `(",", ":")`. `fingerprint_files()` must hash each normalized relative path plus its current bytes. `classify_sensitive()` returns true for `SENSITIVE_PREFIXES`, `SENSITIVE_FILES`, `.env*`, or normalized path components/names containing `trade`, `order`, `broker`, or `mt5`.

`ExecutionLedger.consume_once()` must acquire an exclusive Windows lock, re-read the ledger while locked, reject an existing request id, append one JSON line with `status:"CLAIMED"`, flush and `os.fsync()` before releasing.

- [ ] **Step 4: Run policy tests**

Run: `.\gitnexus\gate-venv\Scripts\python.exe -m pytest tests\test_gitnexus_write_policy.py -q -p no:cacheprovider`  
Expected: all tests PASS.

- [ ] **Step 5: Reviewer checkpoint**

Inspect path traversal, replay and TTL tests. No commit unless separately authorized.

---

### Task 3: MCP proxy and two-phase native writes

**Files:**
- Create: `mcp_gitnexus_gate.py`
- Create: `tests/test_gitnexus_write_gate_mcp.py`

**Interfaces:**
- Downstream command: `node C:\Users\flore\AppData\Roaming\npm\node_modules\gitnexus\dist\cli\index.js mcp`.
- Read-only tools: forwarded with unchanged name, description and schema.
- Controlled rename schema: native fields plus `approval_id`; `dry_run:false` without an approval creates a pending request and performs no write.
- Controlled group sync schema: native fields plus `approval_id`; no approval creates a pending request after group membership validation.
- Produces bus request type `gitnexus_write_request` and result types `PENDING_APPROVAL`, `APPLIED`, `REFUSED`, `VERIFICATION_FAILED`.

- [ ] **Step 1: Write fake-downstream integration tests**

Create a `FakeGitNexus` recording calls and returning deterministic `list_tools`, `list_repos`, `impact`, `rename`, `group_list`, `group_sync` and `detect_changes` results. Cover:

```python
@pytest.mark.asyncio
async def test_rename_prepares_preview_but_never_writes_without_approval(gate):
    result = await gate.rename({
        "repo": "titanium-v12", "symbol_name": "old",
        "new_name": "new", "file_path": "sample.py", "dry_run": False,
    })
    assert result["status"] == "PENDING_APPROVAL"
    assert ("rename", {"dry_run": True}) in simplified_calls(gate.downstream)
    assert not any(args.get("dry_run") is False for name, args in gate.downstream.calls if name == "rename")

@pytest.mark.asyncio
async def test_exact_approval_executes_once_then_detects_changes(gate):
    pending = await prepare_low_risk_rename(gate)
    append_supervisor_approval(gate.acks, pending, actor="codex")
    result = await gate.rename({**pending["args"], "dry_run": False,
                                "approval_id": pending["request_id"]})
    assert result["status"] == "APPLIED"
    assert call_names(gate.downstream)[-2:] == ["rename", "detect_changes"]
    replay = await gate.rename({**pending["args"], "dry_run": False,
                                "approval_id": pending["request_id"]})
    assert replay["status"] == "REFUSED"
    assert replay["reason"] == "APPROVAL_REPLAY"

@pytest.mark.asyncio
async def test_group_sync_refuses_when_no_v12_only_group_exists(gate):
    result = await gate.group_sync({"name": "missing"})
    assert result == {"status": "REFUSED", "reason": "GROUP_NOT_ALLOWED"}
    assert "group_sync" not in call_names(gate.downstream)
```

- [ ] **Step 2: Run MCP tests and verify red**

Run: `.\gitnexus\gate-venv\Scripts\python.exe -m pytest tests\test_gitnexus_write_gate_mcp.py -q -p no:cacheprovider`  
Expected: collection FAIL because `mcp_gitnexus_gate` does not exist.

- [ ] **Step 3: Implement the downstream MCP client**

Create `GitNexusClient` using `StdioServerParameters`, `stdio_client` and `ClientSession`. Each public `call(name, args)` opens a bounded session, calls `initialize()`, then `call_tool()`, rejects `isError`, concatenates text content, removes the GitNexus `--- Next:` suffix, and parses the first JSON object. Timeouts are 30 seconds for read/preview and 120 seconds for an approved write.

Use dependency injection in `GitNexusGate.__init__(downstream, root, stream_path, ack_path, ledger_path, now)` so tests never launch the real server.

- [ ] **Step 4: Implement read forwarding and controlled tools**

Use `Server("titanium-gitnexus-write-gate")`. In `list_tools()`, obtain downstream tools and return unchanged only those whose `annotations.readOnlyHint is True`. Refuse to expose unknown or unannotated tools. Replace only `rename` and `group_sync` descriptions with a `SUPERVISED WRITE` warning and extend their schemas with:

```python
"approval_id": {
    "type": "string",
    "description": "Single-use request id approved by Claude or Codex"
}
```

For rename preparation:

1. force `dry_run=True` downstream;
2. require `status="success"`, `applied=false`, non-empty `changes`;
3. extract every `changes[].file_path`, validate it under V12 and fingerprint it;
4. call downstream `impact` with `target=symbol_name`, `direction="upstream"`, `repo="titanium-v12"`;
5. append the complete immutable request to `collab/messages/stream.ndjson`;
6. return request id, expiry, hash, risk and preview.

For approved execution, remove `approval_id` before canonicalization and before any downstream call, recompute the file fingerprint, validate approvals and ledger claim, call downstream `rename` with the exact prepared arguments and `dry_run=False`, then call `detect_changes(scope="all", repo="titanium-v12", worktree=str(ROOT))`. Any downstream error returns `VERIFICATION_FAILED`; it never triggers an automatic destructive rollback.

For group sync, call `group_list`; require exactly one matching group and every member path equal to V12. With no current groups, return `GROUP_NOT_ALLOWED` before creating a request.

- [ ] **Step 5: Run MCP integration tests**

Run: `.\gitnexus\gate-venv\Scripts\python.exe -m pytest tests\test_gitnexus_write_gate_mcp.py tests\test_gitnexus_write_policy.py -q -p no:cacheprovider`  
Expected: all tests PASS.

- [ ] **Step 6: Reviewer checkpoint**

Claude or Codex reviews that every destructive downstream call is dominated by approval validation and replay claim. No commit unless separately authorized.

---

### Task 4: Configuration split — direct reviewers, gated Hermes

**Files:**
- Modify: `tools/configure_gitnexus_mcp.ps1`
- Modify: `.mcp.json`
- Modify: `tests/test_gitnexus_mcp_config.py`
- Create: `requirements-gitnexus-gate.txt`

**Interfaces:**
- Claude/Codex: existing direct GitNexus server.
- Hermes: `gitnexus` command becomes `.\gitnexus\gate-venv\Scripts\python.exe mcp_gitnexus_gate.py`.
- Gate server launches the exact global GitNexus CLI internally; no `npx`.

- [ ] **Step 1: Write failing configuration contracts**

Add assertions:

```python
def test_claude_can_inspect_the_write_gate_but_keeps_direct_gitnexus():
    cfg = json.loads(Path(".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert cfg["gitnexus"]["command"] == "node"
    assert cfg["gitnexus_write_gate"]["args"][-1].endswith("mcp_gitnexus_gate.py")

def test_hermes_configurator_registers_only_the_local_gate():
    script = Path("tools/configure_gitnexus_mcp.ps1").read_text(encoding="utf-8")
    assert "$GitNexusGate" in script
    assert "mcp_gitnexus_gate.py" in script
    assert 'mcp add gitnexus --command $ProjectPython --args $GitNexusGate' in script
    assert 'mcp add gitnexus --command node --args $GitNexusCli mcp' not in script
```

- [ ] **Step 2: Run configuration tests and verify red**

Run: `.\gitnexus\gate-venv\Scripts\python.exe -m pytest tests\test_gitnexus_mcp_config.py -q -p no:cacheprovider`  
Expected: FAIL because the gate is not declared/configured.

- [ ] **Step 3: Modify project and Hermes configuration commands**

In `.mcp.json`, add:

```json
"gitnexus_write_gate": {
  "command": "C:\\Users\\flore\\Desktop\\v12\\gitnexus\\gate-venv\\Scripts\\python.exe",
  "args": ["C:\\Users\\flore\\Desktop\\v12\\mcp_gitnexus_gate.py"]
}
```

In `tools/configure_gitnexus_mcp.ps1`, retain the direct Codex registration. Define:

```powershell
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ProjectPython = Join-Path $ProjectRoot "gitnexus\gate-venv\Scripts\python.exe"
$GitNexusGate = Join-Path $ProjectRoot "mcp_gitnexus_gate.py"
```

Create `requirements-gitnexus-gate.txt` with exact pins `mcp==1.28.1`, `pytest==9.1.1`, and `pytest-asyncio==1.4.0`. The configurator must fail closed if `$ProjectPython` is absent; environment creation is an explicit setup step using the installed `uv` runtime, never an implicit network action during an MCP launch.

Replace only the Hermes `mcp add gitnexus` command with:

```powershell
"Y" | & $Hermes mcp add gitnexus --command $ProjectPython --args $GitNexusGate
```

- [ ] **Step 4: Run configuration and bridge tests**

Run: `.\gitnexus\gate-venv\Scripts\python.exe -m pytest tests\test_gitnexus_mcp_config.py tests\test_hermes_bridge_config.py -q -p no:cacheprovider`  
Expected: all tests PASS.

- [ ] **Step 5: Reviewer checkpoint**

Inspect `.mcp.json` for secrets and verify Claude/Codex direct access is unchanged. No commit unless separately authorized.

---

### Task 5: Operational documentation and activation rehearsal

**Files:**
- Modify: `collab/HERMES_BRIDGE.md`
- Modify: `collab/governance/OPERATING_MODEL.md`
- Modify: `collab/TASKS.md`
- Modify: `collab/LOG.md`
- Test: `tests/test_gitnexus_write_policy.py`
- Test: `tests/test_gitnexus_write_gate_mcp.py`

**Interfaces:**
- Runbook names the request, approval, execution and review commands.
- Rollback removes Hermes's gate registration and restores the direct read-only configuration only after an explicit user decision.

- [ ] **Step 1: Document the exact supervised workflow**

Add this operator sequence to `collab/HERMES_BRIDGE.md`:

```text
1. Hermes calls rename/group_sync without approval_id → PENDING_APPROVAL.
2. Claude or Codex verifies context, impact, preview and args_sha256.
3. Supervisor runs:
   node tools/collab_bus.mjs approve-write --from <claude|codex> \
     --for <request_id> --tool <rename|group_sync> --args-sha256 <sha256>
4. For sensitive/HIGH/CRITICAL only, Florent also supplies a request-specific
   approval recorded with --from florent --florent-override.
5. Hermes repeats the exact tool call with approval_id=<request_id>.
6. Gate returns APPLIED plus detect_changes evidence.
7. Claude or Codex records ACCEPTED, REQUEST_CHANGES or ROLLBACK_REQUIRED.
```

Document that `group_sync` is active-but-refusing while `group_list` is empty.

- [ ] **Step 2: Run the complete offline suite**

Run:

```powershell
.\gitnexus\gate-venv\Scripts\python.exe -m pytest tests\test_gitnexus_write_policy.py tests\test_gitnexus_write_gate_mcp.py tests\test_gitnexus_mcp_config.py tests\test_hermes_bridge_config.py -q -p no:cacheprovider
node --test tests/test_collab_bus.mjs
```

Expected: all Python and Node tests PASS.

- [ ] **Step 3: Perform a no-write real MCP rehearsal**

Run the gate server through an MCP client and call:

1. `list_repos` — expect `titanium-v12` and `jarvis-runtime`.
2. `rename` for `account_snapshot` with `new_name="account_snapshot_preview_DO_NOT_APPLY"` and no approval — expect `PENDING_APPROVAL`, `applied:false`, and no git diff change.
3. `group_sync(name="missing")` — expect `REFUSED/GROUP_NOT_ALLOWED`.
4. `detect_changes` — expect no change caused by the rehearsal.

Never approve or apply the rehearsal rename.

- [ ] **Step 4: Activate Hermes only after reviewer approval**

Run `tools/configure_gitnexus_mcp.ps1`, restart the Hermes session, then verify:

```powershell
& "C:\Users\flore\AppData\Local\hermes\hermes-agent\venv\Scripts\hermes.exe" mcp test gitnexus
```

Expected: connected to `titanium-gitnexus-write-gate`; read tools work; `rename` and `group_sync` advertise `SUPERVISED WRITE`.

- [ ] **Step 5: Final GitNexus change detection and status**

Run direct reviewer-side GitNexus `detect_changes(scope="all", repo="titanium-v12", worktree="C:\\Users\\flore\\Desktop\\v12")`. Confirm only the planned gate/config/test/docs files are affected. Record the result in `collab/LOG.md` and set the task to `REVIEW`, never `DONE`.

- [ ] **Step 6: Commit only under separate authorization**

Without a new explicit commit instruction, stop with a reviewed working tree. If Florent separately authorizes a commit:

```powershell
git add mcp_gitnexus_gate.py tools/gitnexus_write_policy.py tools/collab_bus.mjs tools/configure_gitnexus_mcp.ps1 tests/test_gitnexus_write_policy.py tests/test_gitnexus_write_gate_mcp.py tests/test_collab_bus.mjs tests/test_gitnexus_mcp_config.py .mcp.json collab/HERMES_BRIDGE.md collab/governance/OPERATING_MODEL.md collab/TASKS.md collab/LOG.md
git commit -m "feat: gate Hermes GitNexus native writes"
```
