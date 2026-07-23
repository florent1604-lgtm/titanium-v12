import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const script = join(root, "tools", "collab_bus.mjs");

function run(busFile, ...args) {
  return JSON.parse(execFileSync(process.execPath, [script, ...args], {
    cwd: root,
    encoding: "utf8",
    env: { ...process.env, COLLAB_BUS_FILE: busFile },
  }));
}

test("append-only collaboration bus sends, reads, and acknowledges a handoff", async () => {
  const dir = await mkdtemp(join(tmpdir(), "titanium-collab-"));
  const busFile = join(dir, "messages.jsonl");

  const sent = run(
    busFile,
    "send",
    "--from", "Codex",
    "--to", "Claude",
    "--type", "handoff",
    "--task", "M1",
    "--body", "Strategy contract ready for review.",
  );

  assert.equal(sent.from, "Codex");
  assert.equal(sent.to, "Claude");
  assert.equal(sent.type, "handoff");
  assert.equal(sent.task, "M1");
  assert.match(sent.id, /^[0-9a-f-]{36}$/i);

  const inbox = run(busFile, "read", "--to", "Claude");
  assert.equal(inbox.messages.length, 1);
  assert.equal(inbox.messages[0].id, sent.id);

  const ack = run(
    busFile,
    "ack",
    "--from", "Claude",
    "--for", sent.id,
    "--body", "Received.",
  );
  assert.equal(ack.type, "ack");
  assert.equal(ack.in_reply_to, sent.id);
  assert.equal(ack.to, "Codex");

  const codexInbox = run(busFile, "read", "--to", "Codex");
  assert.equal(codexInbox.messages.length, 1);
  assert.equal(codexInbox.messages[0].id, ack.id);

  const lines = (await readFile(busFile, "utf8")).trim().split("\n");
  assert.equal(lines.length, 2);
  assert.equal(JSON.parse(lines[0]).id, sent.id);
  assert.equal(JSON.parse(lines[1]).id, ack.id);
});

test("approve-write imports a complete detached Ed25519 approval", async () => {
  const dir = await mkdtemp(join(tmpdir(), "titanium-gate-"));
  const busFile = join(dir, "messages.jsonl");
  const requestId = "11111111-1111-4111-8111-111111111111";
  const digest = "a".repeat(64);
  const fingerprint = "b".repeat(64);
  const approvalId = "22222222-2222-4222-8222-222222222222";
  const approvedAt = "2026-07-13T12:00:00.000Z";
  const expiresAt = "2026-07-13T12:15:00.000Z";
  const nonce = "c".repeat(32);
  const signature = Buffer.alloc(64, 7).toString("base64");

  const approval = run(
    busFile,
    "approve-write",
    "--from", "codex",
    "--approval-id", approvalId,
    "--for", requestId,
    "--ts-utc", approvedAt,
    "--tool", "rename",
    "--args-sha256", digest,
    "--file-fingerprint", fingerprint,
    "--request-expires-ts", expiresAt,
    "--nonce", nonce,
    "--key-id", "codex-hardware-1",
    "--signature-b64", signature,
  );

  assert.equal(approval.id, approvalId);
  assert.equal(approval.type, "gitnexus_write_approval");
  assert.equal(approval.verdict, "APPROVED");
  assert.equal(approval.in_reply_to, requestId);
  assert.equal(approval.to, "hermes");
  assert.equal(approval.args_sha256, digest);
  assert.equal(approval.file_fingerprint, fingerprint);
  assert.equal(approval.request_expires_ts, expiresAt);
  assert.equal(approval.nonce, nonce);
  assert.deepEqual(approval.signature, {
    algorithm: "Ed25519",
    key_id: "codex-hardware-1",
    value_b64: signature,
  });
  assert.equal(approval.florent_override, false);
});

test("approve-write rejects unknown supervisors and malformed hashes", async () => {
  const dir = await mkdtemp(join(tmpdir(), "titanium-gate-"));
  const busFile = join(dir, "messages.jsonl");

  assert.throws(() => run(
    busFile,
    "approve-write",
    "--from", "hermes",
    "--for", "req",
    "--tool", "rename",
    "--args-sha256", "bad",
  ));

  assert.throws(() => run(
    busFile,
    "approve-write",
    "--from", "codex",
    "--approval-id", "22222222-2222-4222-8222-222222222222",
    "--for", "11111111-1111-4111-8111-111111111111",
    "--ts-utc", "2026-07-13T12:00:00.000Z",
    "--tool", "rename",
    "--args-sha256", "a".repeat(64),
    "--file-fingerprint", "b".repeat(64),
    "--request-expires-ts", "2026-07-13T12:15:00.000Z",
    "--nonce", "c".repeat(32),
  ));
});
