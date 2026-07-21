$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Hermes = Join-Path $env:LOCALAPPDATA "hermes\hermes-agent\venv\Scripts\hermes.exe"
$GitNexusRuntime = Join-Path $ProjectRoot "tools\gitnexus_mcp_bootstrap.mjs"
$ProjectPython = Join-Path $ProjectRoot "gitnexus\gate-venv\Scripts\python.exe"
$GitNexusGate = Join-Path $ProjectRoot "mcp_gitnexus_gate.py"
$ClaudeGitNexusEndpoint = "http://127.0.0.1:4747/api/mcp"
$GitNexusGateEndpoint = "http://127.0.0.1:4750/mcp"
$Claude = Get-ChildItem -Path (
    Join-Path $env:USERPROFILE ".vscode\extensions\anthropic.claude-code-*-win32-x64\resources\native-binary\claude.exe"
) -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 -ExpandProperty FullName
$IdentityTool = Join-Path $ProjectRoot "tools\claude_gitnexus_identity.py"

if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    throw "Codex CLI introuvable dans PATH"
}
if (-not (Test-Path -LiteralPath $Hermes)) {
    throw "Hermes CLI introuvable: $Hermes"
}
if (-not (Test-Path -LiteralPath $GitNexusRuntime -PathType Leaf)) {
    throw "Runtime GitNexus local introuvable: $GitNexusRuntime"
}
if (-not (Test-Path -LiteralPath $ProjectPython -PathType Leaf)) {
    throw "Environnement Python du garde introuvable: $ProjectPython"
}
if (-not (Test-Path -LiteralPath $GitNexusGate -PathType Leaf)) {
    throw "Serveur du garde GitNexus introuvable: $GitNexusGate"
}
if (-not $Claude -or -not (Test-Path -LiteralPath $Claude -PathType Leaf)) {
    throw "Claude Code CLI introuvable"
}
if (-not (Test-Path -LiteralPath $IdentityTool -PathType Leaf)) {
    throw "Garde identite Claude introuvable: $IdentityTool"
}

$ClaudeServers = (& $Claude mcp list 2>&1 | Out-String)
if ($ClaudeServers -match "(?m)^gitnexus:") {
    & $Claude mcp remove gitnexus --scope user | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Echec remplacement MCP GitNexus dans Claude" }
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
    & $Claude mcp remove gitnexus --scope user | Out-Null
    throw "Claude n'est pas en mode abonnement sur: repli Ollama requis"
}

$CodexServers = (& codex mcp list 2>&1 | Out-String)
if ($CodexServers -match "(?m)^gitnexus\b") {
    & codex mcp remove gitnexus
    if ($LASTEXITCODE -ne 0) { throw "Échec remplacement MCP GitNexus dans Codex" }
}
& codex mcp add gitnexus --url $ClaudeGitNexusEndpoint
if ($LASTEXITCODE -ne 0) { throw "Échec ajout MCP GitNexus à Codex" }

$HermesServers = (& $Hermes mcp list 2>&1 | Out-String)
if ($HermesServers -match "(?m)^\s*gitnexus\b") {
    & $Hermes mcp remove gitnexus
    if ($LASTEXITCODE -ne 0) { throw "Échec remplacement MCP GitNexus dans Hermes" }
}
"Y" | & $Hermes mcp add gitnexus --url $GitNexusGateEndpoint
$HermesAfter = (& $Hermes mcp list 2>&1 | Out-String)
if ($HermesAfter -notmatch "(?m)^\s*gitnexus\b") {
    throw "Échec ajout MCP GitNexus à Hermes : serveur absent de la configuration après confirmation"
}

$HermesTest = (& $Hermes mcp test gitnexus 2>&1 | Out-String)
if ($HermesTest -notmatch "Connected") {
    throw "Handshake MCP GitNexus/Hermes en échec : $HermesTest"
}

Write-Output "Claude: GitNexus HTTP loopback configure en native-read-only."
Write-Output "Codex: GitNexus HTTP loopback configure sans serveur enfant."
Write-Output "Hermes: garde GitNexus HTTP singleton supervise configure et connecte."
Write-Output "Relancer les sessions Claude/Codex ouvertes pour charger le nouveau serveur."
