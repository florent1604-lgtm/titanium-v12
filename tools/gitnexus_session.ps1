param(
    [switch]$OpenBrowser,
    [switch]$NoWatch
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Runtime = Join-Path $PSScriptRoot "gitnexus_runtime.py"
$Candidates = @()
if (Get-Command uv -ErrorAction SilentlyContinue) {
    try {
        $UvPython = (& uv python find 3.11 2>$null | Select-Object -First 1)
        if ($LASTEXITCODE -eq 0 -and $UvPython) { $Candidates += $UvPython.Trim() }
    } catch {}
}
$Candidates += @(
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
    (Join-Path $ProjectRoot "venv\Scripts\python.exe"),
    "python"
)
$Python = $null
foreach ($Candidate in $Candidates) {
    try {
        & $Candidate --version *> $null
        if ($LASTEXITCODE -eq 0) { $Python = $Candidate; break }
    } catch {}
}
if (-not $Python) { throw "Python 3.11+ introuvable" }

$RuntimeArgs = @($Runtime, "session")
if ($OpenBrowser) { $RuntimeArgs += "--open-browser" }
if ($NoWatch) { $RuntimeArgs += "--no-watch" }

& $Python @RuntimeArgs
exit $LASTEXITCODE
