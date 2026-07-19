#!/usr/bin/env node

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

// LadybugDB's Windows FTS extension depends on the OpenSSL 3 DLLs shipped
// with Git for Windows. The native loader does not search the extension's
// own directory, so make that dependency visible before importing the native
// binding. GITNEXUS_OPENSSL_BIN remains available for non-standard installs.
if (process.platform === "win32") {
  const opensslBin =
    process.env.GITNEXUS_OPENSSL_BIN?.trim() ||
    "C:\\Program Files\\Git\\mingw64\\bin";

  if (existsSync(opensslBin)) {
    const currentPath = process.env.PATH || "";
    const pathEntries = currentPath.split(path.delimiter).filter(Boolean);
    const alreadyPresent = pathEntries.some(
      (entry) => entry.toLowerCase() === opensslBin.toLowerCase(),
    );
    if (!alreadyPresent) {
      process.env.PATH = `${opensslBin}${path.delimiter}${currentPath}`;
    }
  }
}

// Keep MCP clients on the same validated GitNexus build as the HTTP server.
// The former project-local 1.6.9 copy crashes on Windows BM25/detect_changes.
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
  throw new Error(`Unsupported GitNexus MCP runtime ${version}; expected 1.6.10-rc.50`);
}
const moduleUrl = (relativePath) =>
  pathToFileURL(path.join(gitnexusRoot, relativePath)).href;

// Preload the native binding before GitNexus installs its stdout sentinel.
await import(moduleUrl("node_modules/@ladybugdb/core/index.js"));

const { installGlobalStdoutSentinel } = await import(
  moduleUrl("dist/mcp/stdio-context.js")
);
installGlobalStdoutSentinel();

const [{ LocalBackend }, { startMCPServer }] = await Promise.all([
  import(moduleUrl("dist/mcp/local/local-backend.js")),
  import(moduleUrl("dist/mcp/server.js")),
]);

const backend = new LocalBackend();
await backend.init();
await startMCPServer(backend);
