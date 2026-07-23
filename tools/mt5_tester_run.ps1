# Safe compatibility entrypoint for native MT5 validation.
#
# This wrapper ONLY validates a manifest and prepares immutable artifacts.
# It never stops/restarts MetaTrader and never touches the Titanium live data dir.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Manifest,

    [string]$RunsRoot = "validation\runs",

    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runner = Join-Path $PSScriptRoot "mt5_tester_runner.py"
$ManifestPath = (Resolve-Path -LiteralPath $Manifest).Path

if (-not $PythonExe) {
    $PythonExe = Join-Path $ProjectRoot "venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Python introuvable. Passez -PythonExe avec un interpréteur Python 3.11+ valide."
}

Write-Warning "Mode sûr : préparation uniquement. Aucun agent ni terminal MT5 ne sera lancé."
& $PythonExe $Runner prepare $ManifestPath --runs-root $RunsRoot
if ($LASTEXITCODE -ne 0) {
    throw "La préparation MT5 native a échoué (code $LASTEXITCODE)."
}
