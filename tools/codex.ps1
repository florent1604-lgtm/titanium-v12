# tools/codex.ps1 — Envoyer un brief à Codex (gpt-5.6-terra) en non-interactif.
# Usage : powershell -File tools\codex.ps1 "ton message" [-Effort medium]
# La réponse s'affiche ; Codex peut aussi écrire dans le repo (sandbox workspace-write).
param(
  [Parameter(Mandatory = $true, Position = 0)][string]$Prompt,
  [string]$Effort = "medium"
)
# Sélectionne une install COMPLÈTE (dont le dossier contient codex-code-mode-host.exe,
# requis pour lire des fichiers / lancer des outils), la plus récente. Évite les
# installs partielles (ex. a7c12 = seulement codex.exe) qui échouent avec
# "code-mode-host introuvable" (os error 2).
$root = "C:\Users\flore\AppData\Local\OpenAI\Codex\bin"
$bin = Get-ChildItem $root -Recurse -Filter codex.exe -ErrorAction SilentlyContinue |
  Where-Object { Test-Path (Join-Path $_.DirectoryName "codex-code-mode-host.exe") } |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1
if (-not $bin) {
  $bin = Get-ChildItem $root -Recurse -Filter codex.exe -ErrorAction SilentlyContinue | Select-Object -First 1
}
if (-not $bin) { Write-Error "codex.exe introuvable sous $root"; exit 1 }
& $bin.FullName exec -c "model_reasoning_effort=$Effort" $Prompt
