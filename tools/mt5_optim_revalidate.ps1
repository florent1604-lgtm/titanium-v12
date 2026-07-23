# mt5_optim_revalidate.ps1 — Re-validation tester natif MT5 des configs par actif
# trouvees par tools/asset_optimizer.py. Lit data/asset_configs.json, isole le
# top 5 (ou -Symbols passe), lance UN test natif par actif AVEC SES VARIABLES
# (SL, ladder TP, align/RSI, TF, time-stop) via [TesterInputs]. Fills reels Axi.
# Rapports HTML -> docs/mt5_opt_reports/.  MT5 = donnees seulement (compte intouche).
param(
  [string[]]$Symbols = @("XAUUSD","USTECH","NAS100.fs","XAUEUR","HSI.fs"),
  [string]$FromDate = "2023.01.01",
  [string]$ToDate   = "2026.07.08"
)
$ErrorActionPreference = "Continue"
$term    = "C:\Program Files\MetaTrader 5\terminal64.exe"
$dataDir = "C:\Users\flore\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075"
$root    = "C:\Users\flore\Desktop\v12"
$outDir  = "$root\docs\mt5_opt_reports"
New-Item -ItemType Directory -Force $outDir | Out-Null

$cfg = Get-Content "$root\data\asset_configs.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$hoursPerBar = @{ "H1" = 1; "H4" = 4; "M15" = 0.25 }

taskkill /IM terminal64.exe /F 2>$null
Start-Sleep -Seconds 4

foreach ($sym in $Symbols) {
  $c = $cfg.assets.$sym
  if (-not $c) { Write-Output "=== $sym : ABSENT de asset_configs.json, saute"; continue }
  $tp = $c.tp_ladder
  $tsHours = [int]([double]$c.time_stop_bars * [double]$hoursPerBar[$c.tf])
  $align = if ($c.align_ema50) { "true" } else { "false" }
  $rsi   = if ($c.rsi_gate)    { "true" } else { "false" }
  $report = "TitaniumOpt_" + ($sym -replace '\.','_')
  Write-Output "=== $sym ($($c.style) $($c.tf)) SLx$($c.sl_atr) TP$($tp -join '/') align=$align rsi=$rsi ts=${tsHours}h"

  $ini = @"
[Tester]
Expert=TitaniumV3
Symbol=$sym
Period=$($c.tf)
FromDate=$FromDate
ToDate=$ToDate
Model=1
Deposit=10000
Currency=EUR
Leverage=100
Report=$report
ShutdownTerminal=1
UseCloud=0
[TesterInputs]
SL_ATR=$($c.sl_atr)
TP1_ATR=$($tp[0])
TP2_ATR=$($tp[1])
TP3_ATR=$($tp[2])
TIME_STOP_HOURS=$tsHours
USE_ALIGN=$align
USE_RSI_GATE=$rsi
USE_SESSION=false
RISK_PCT=1.0
"@
  $iniPath = "$env:TEMP\opt_$($sym -replace '\.','_').ini"
  $ini | Out-File -FilePath $iniPath -Encoding Unicode
  $p = Start-Process -FilePath $term -ArgumentList "/config:`"$iniPath`"" -PassThru
  $p.WaitForExit(600000) | Out-Null
  if (-not $p.HasExited) { $p.Kill(); Write-Output "$sym : TIMEOUT" }
  Start-Sleep -Seconds 3
  $found = $null
  foreach ($r in @($dataDir, "C:\Program Files\MetaTrader 5")) {
    $f = Get-ChildItem -Path $r -Filter "$report*.htm*" -ErrorAction SilentlyContinue |
         Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($f) { $found = $f; break }
  }
  if ($found) {
    Copy-Item $found.FullName "$outDir\$report.html" -Force
    Write-Output "$sym : rapport -> docs\mt5_opt_reports\$report.html ($([math]::Round($found.Length/1kb)) ko)"
  } else {
    Write-Output "$sym : RAPPORT INTROUVABLE"
  }
}
Start-Process -FilePath $term
Write-Output "Terminal MT5 relance."
