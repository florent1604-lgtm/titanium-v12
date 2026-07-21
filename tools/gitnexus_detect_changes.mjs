#!/usr/bin/env node

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

// LadybugDB can crash on Windows when the native process writes through an
// anonymous stdout pipe. The Python gate uses disk-backed temporary handles.
// Load the same pinned global runtime as the HTTP server and MCP bootstrap so
// a clean checkout never depends on the obsolete ignored project runtime.
const gitnexusRoot = path.join(
  process.env.APPDATA || path.join(process.env.USERPROFILE || "", "AppData", "Roaming"),
  "npm", "node_modules", "gitnexus",
);
const packagePath = path.join(gitnexusRoot, "package.json");
if (!existsSync(packagePath)) {
  throw new Error(`Global GitNexus runtime not found: ${packagePath}`);
}
const { version } = JSON.parse(readFileSync(packagePath, "utf8"));
if (version !== "1.6.10-rc.50") {
  throw new Error(`Unsupported GitNexus runtime ${version}; expected 1.6.10-rc.50`);
}
const moduleUrl = (relativePath) =>
  pathToFileURL(path.join(gitnexusRoot, relativePath)).href;

await import(moduleUrl("node_modules/@ladybugdb/core/index.js"));
const { LocalBackend } = await import(
  moduleUrl("dist/mcp/local/local-backend.js")
);

const allowedScopes = new Set(["all", "staged", "unstaged"]);
const requestedScope = process.argv[2] || "all";
if (!allowedScopes.has(requestedScope)) {
  throw new Error(`Unsupported detect_changes scope: ${requestedScope}`);
}

const backend = new LocalBackend();
try {
  await backend.init();
  const result = await backend.callTool("detect_changes", {
    scope: requestedScope,
    repo: "titanium-v12",
  });
  process.stdout.write(JSON.stringify(result));
} finally {
  await backend.dispose();
}
