[CmdletBinding()]
param(
    [switch]$InstallOnly,
    [switch]$SkipTests,
    [string]$PythonVersion = "3.12",
    [string]$VenvDir = "venv"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

$VenvPython = Join-Path $ProjectRoot "$VenvDir\Scripts\python.exe"

Write-Host "[Titanium] Project root: $ProjectRoot"

if (-not (Test-Path $VenvPython)) {
    Write-Host "[Titanium] Creating virtual environment ($VenvDir) with Python $PythonVersion..."
    py -$PythonVersion -m venv $VenvDir
}

if (-not (Test-Path $VenvPython)) {
    throw "Virtual environment was not created. Check Python launcher and version (py -0p)."
}

& $VenvPython -m pip install --upgrade pip setuptools wheel
& $VenvPython -m pip install -r requirements.txt

if ((Test-Path "requirements-test.txt") -and (-not $SkipTests)) {
    & $VenvPython -m pip install -r requirements-test.txt
}

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[Titanium] .env created from .env.example"
    Write-Host "[Titanium] Edit .env with your keys if needed."
}

if ($InstallOnly) {
    Write-Host "[Titanium] Install-only mode complete."
    Write-Host "[Titanium] To run: $VenvPython main.py"
    exit 0
}

if (-not $SkipTests) {
    Write-Host "[Titanium] Running smoke tests..."
    & $VenvPython -m pytest -q tests/test_main_startup.py tests/test_api_state_json_contract.py
}

# Prevent accidental conflict with an already running live instance on 8090.
$portInUse = Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue
if ($portInUse) {
    Write-Warning "Port 8090 is already in use. If live bot is running, use -InstallOnly on this machine."
    exit 1
}

Write-Host "[Titanium] Starting app on http://127.0.0.1:8090"
& $VenvPython main.py