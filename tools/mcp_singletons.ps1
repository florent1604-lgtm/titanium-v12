param(
    [ValidateSet("start", "status", "stop")]
    [string]$Action = "status"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runtime = Join-Path $Root "data\runtime\mcp"
$McpPython = Join-Path $Root "gitnexus\gate-venv\Scripts\python.exe"

$Services = @(
    [pscustomobject]@{
        Name = "gitnexus-write-gate"; Port = 4750; Python = $McpPython
        Script = Join-Path $Root "mcp_gitnexus_gate.py"
    },
    [pscustomobject]@{
        Name = "titanium-mcp"; Port = 8091; Python = $McpPython
        Script = Join-Path $Root "tools\titanium_mcp_http.py"
    },
    [pscustomobject]@{
        Name = "hermes-mcp"; Port = 8766; Python = $McpPython
        Script = Join-Path $Root "tools\hermes_mcp_http.py"
    }
)

function Get-ListenerPid([int]$Port) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $listener) { return [int]$listener.OwningProcess }

    # Une session non elevee ne voit pas toujours le proprietaire d'un socket
    # ouvert par un processus eleve. Le probe TCP evite alors un faux DOWN et,
    # surtout, interdit a `start` de creer un doublon sur le meme port.
    $tcp = [System.Net.Sockets.TcpClient]::new()
    try {
        $connect = $tcp.ConnectAsync("127.0.0.1", $Port)
        if ($connect.Wait(750) -and $tcp.Connected) {
            return 0 # Listener visible, PID masque par Windows.
        }
    } catch {
        return $null
    } finally {
        $tcp.Dispose()
    }
    return $null
}

function Get-PidPath($Service) {
    return Join-Path $Runtime ($Service.Name + ".json")
}

function Assert-ServiceFiles($Service) {
    if (-not (Test-Path -LiteralPath $Service.Python -PathType Leaf)) {
        throw "Python absent pour $($Service.Name): $($Service.Python)"
    }
    if (-not (Test-Path -LiteralPath $Service.Script -PathType Leaf)) {
        throw "Script absent pour $($Service.Name): $($Service.Script)"
    }
}

if ($Action -eq "start") {
    New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
    foreach ($service in $Services) {
        Assert-ServiceFiles $service
        $existing = Get-ListenerPid $service.Port
        if ($null -ne $existing) {
            $owner = if ($existing -eq 0) { "masque" } else { [string]$existing }
            Write-Output "$($service.Name): deja actif pid=$owner port=$($service.Port)"
            continue
        }
        $stdout = Join-Path $Runtime ($service.Name + ".stdout.log")
        $stderr = Join-Path $Runtime ($service.Name + ".stderr.log")
        $process = Start-Process -FilePath $service.Python -ArgumentList @($service.Script) `
            -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        [pscustomobject]@{
            name = $service.Name; pid = $process.Id; port = $service.Port
            python = $service.Python; script = $service.Script
            started_at = [DateTime]::UtcNow.ToString("o")
        } | ConvertTo-Json | Set-Content -LiteralPath (Get-PidPath $service) -Encoding UTF8
        Write-Output "$($service.Name): lance pid=$($process.Id) port=$($service.Port)"
    }
    exit 0
}

if ($Action -eq "stop") {
    $runtimeResolved = [IO.Path]::GetFullPath($Runtime)
    foreach ($service in $Services) {
        $pidPath = [IO.Path]::GetFullPath((Get-PidPath $service))
        if (-not $pidPath.StartsWith($runtimeResolved, [StringComparison]::OrdinalIgnoreCase)) {
            throw "PID path hors runtime: $pidPath"
        }
        if (-not (Test-Path -LiteralPath $pidPath -PathType Leaf)) {
            Write-Output "$($service.Name): aucun pid gere"
            continue
        }
        $record = Get-Content -LiteralPath $pidPath -Encoding UTF8 | ConvertFrom-Json
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($record.pid)" -ErrorAction SilentlyContinue
        if ($null -ne $process) {
            $expected = [IO.Path]::GetFullPath($service.Script)
            if ([string]$process.CommandLine -notlike "*$expected*") {
                throw "Refus arret $($service.Name): PID reutilise ou commande inattendue"
            }
            Stop-Process -Id $record.pid -Force
            Write-Output "$($service.Name): arrete pid=$($record.pid)"
        }
        Remove-Item -LiteralPath $pidPath -Force
    }
    exit 0
}

foreach ($service in $Services) {
    $listenerPid = Get-ListenerPid $service.Port
    if ($null -eq $listenerPid) {
        Write-Output "$($service.Name): DOWN port=$($service.Port)"
    } else {
        $owner = if ($listenerPid -eq 0) { "masque" } else { [string]$listenerPid }
        Write-Output "$($service.Name): UP pid=$owner port=$($service.Port)"
    }
}
