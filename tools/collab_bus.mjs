#!/usr/bin/env node
/**
 * Local Claude <-> Codex append-only message bus.
 *
 * No network, no child process, no secret. The stream is deliberately human
 * inspectable so LOG.md remains the decision record and this file is only the
 * transport/acknowledgement layer.
 */
import { appendFile, mkdir, readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";

// `URL.pathname` is `/C:/...` on Windows; convert the module URL first so the
// stream is always resolved inside this repository on every platform.
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const overrideFile = process.env.COLLAB_BUS_FILE
  ? resolve(process.env.COLLAB_BUS_FILE)
  : null;
const defaultStream = overrideFile || resolve(root, "collab", "messages", "stream.ndjson");
const defaultAck = overrideFile || resolve(root, "collab", "messages", "acks.ndjson");

function usage() {
  console.error([
    "Usage:",
    '  node tools/collab_bus.mjs send --from codex --to claude --task M1 --content "..."',
    '  node tools/collab_bus.mjs ack --from claude --for <id> --body "..."',
    "  node tools/collab_bus.mjs approve-write --from <claude|codex|florent> --approval-id <uuid> --for <request-id> --ts-utc <iso> --tool <rename|group_sync> --args-sha256 <sha256> --file-fingerprint <sha256> --request-expires-ts <iso> --nonce <value> --key-id <id> --signature-b64 <ed25519-signature>",
    "  node tools/collab_bus.mjs tail [--acks] [--limit 20]",
    "  node tools/collab_bus.mjs read <id> [--acks]",
  ].join("\n"));
  process.exitCode = 2;
}

function args(argv) {
  const out = { _: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith("--")) {
      out._.push(token);
      continue;
    }
    const key = token.slice(2);
    const next = argv[i + 1];
    if (next && !next.startsWith("--")) {
      out[key] = next;
      i += 1;
    } else {
      out[key] = true;
    }
  }
  return out;
}

function required(values, names) {
  for (const name of names) {
    if (!values[name] || typeof values[name] !== "string") {
      throw new Error("Missing --" + name);
    }
  }
}

async function append(path, value) {
  await mkdir(dirname(path), { recursive: true });
  await appendFile(path, JSON.stringify(value) + "\n", { encoding: "utf8" });
}

async function load(path) {
  try {
    const raw = await readFile(path, "utf8");
    return raw.split(/\r?\n/).filter(Boolean).flatMap((line) => {
      try { return [JSON.parse(line)]; } catch { return []; }
    });
  } catch (error) {
    if (error.code === "ENOENT") return [];
    throw error;
  }
}

const values = args(process.argv.slice(2));
const command = values._[0];
const WRITE_SUPERVISORS = new Set(["claude", "codex", "florent"]);
const WRITE_TOOLS = new Set(["rename", "group_sync"]);

try {
  if (command === "approve-write") {
    required(values, [
      "from", "approval-id", "for", "ts-utc", "tool", "args-sha256",
      "file-fingerprint", "request-expires-ts", "nonce", "key-id",
      "signature-b64",
    ]);
    const from = values.from.toLowerCase();
    if (!WRITE_SUPERVISORS.has(from)) throw new Error("Invalid write supervisor");
    if (!WRITE_TOOLS.has(values.tool)) throw new Error("Invalid GitNexus write tool");
    for (const name of ["args-sha256", "file-fingerprint"]) {
      if (!/^[0-9a-f]{64}$/i.test(values[name])) {
        throw new Error("Invalid --" + name);
      }
    }
    for (const name of ["ts-utc", "request-expires-ts"]) {
      if (!Number.isFinite(Date.parse(values[name])) || !/[zZ]|[+-]\d\d:\d\d$/.test(values[name])) {
        throw new Error("Invalid --" + name);
      }
    }
    if (values.nonce.length < 16 || values.nonce.length > 128) {
      throw new Error("Invalid --nonce");
    }
    if (!/^[A-Za-z0-9._:-]{1,128}$/.test(values["key-id"])) {
      throw new Error("Invalid --key-id");
    }
    if (!/^[A-Za-z0-9+/]{86}==$/.test(values["signature-b64"])
        || Buffer.from(values["signature-b64"], "base64").length !== 64) {
      throw new Error("Invalid --signature-b64");
    }
    const message = {
      id: values["approval-id"],
      type: "gitnexus_write_approval",
      verdict: "APPROVED",
      from,
      to: "hermes",
      task: "GITNEXUS_WRITE",
      in_reply_to: values.for,
      ts_utc: values["ts-utc"],
      tool: values.tool,
      args_sha256: values["args-sha256"].toLowerCase(),
      file_fingerprint: values["file-fingerprint"].toLowerCase(),
      request_expires_ts: values["request-expires-ts"],
      nonce: values.nonce,
      florent_override: from === "florent" && values["florent-override"] === true,
      signature: {
        algorithm: "Ed25519",
        key_id: values["key-id"],
        value_b64: values["signature-b64"],
      },
      content: "APPROVED",
      body: "APPROVED",
    };
    await append(defaultAck, message);
    console.log(JSON.stringify(message));
  } else if (command === "send" || command === "ack") {
    const content = values.content || values.body;
    required(values, ["from"]);
    if (!content || typeof content !== "string") {
      throw new Error("Missing --content or --body");
    }
    const replyTo = values["in-reply-to"] || values.for || null;
    if (command === "ack" && !replyTo) {
      throw new Error("Missing --in-reply-to or --for");
    }
    let to = values.to;
    if (command === "ack" && !to && replyTo) {
      const original = (await load(defaultStream)).find((item) => item.id === replyTo);
      to = original && original.from;
    }
    required({ to }, ["to"]);
    const now = new Date().toISOString();
    const message = {
      id: randomUUID(),
      type: command === "ack" ? "ack" : (values.type || "message"),
      from: values.from,
      to,
      task: values.task || null,
      in_reply_to: replyTo,
      ts_utc: now,
      content,
      body: content,
    };
    await append(command === "ack" ? defaultAck : defaultStream, message);
    console.log(JSON.stringify(message));
  } else if (command === "tail") {
    const path = values.acks ? defaultAck : defaultStream;
    const limit = Math.max(1, Number(values.limit || 20));
    const messages = await load(path);
    console.log(messages.slice(-limit).map((item) => JSON.stringify(item)).join("\n"));
  } else if (command === "read") {
    const id = values._[1];
    const paths = overrideFile
      ? [defaultStream]
      : (values.to ? [defaultStream, defaultAck]
        : (values.acks ? [defaultAck] : [defaultStream]));
    const messages = (await Promise.all(paths.map((path) => load(path)))).flat();
    if (values.to) {
      console.log(JSON.stringify({
        messages: messages.filter((item) => item.to === values.to),
      }));
    } else if (!id) {
      throw new Error("Missing message id or --to");
    } else {
      const message = messages.find((item) => item.id === id);
      if (!message) {
        console.error("Message not found: " + id);
        process.exitCode = 1;
      } else {
        console.log(JSON.stringify(message));
      }
    }
  } else {
    usage();
  }
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
