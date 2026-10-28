[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,

    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$Url = "http://127.0.0.1:$Port"
$Server = $null

function Test-PortInUse {
    param([int]$TargetPort)
    $Client = [System.Net.Sockets.TcpClient]::new()
    try {
        $Task = $Client.ConnectAsync('127.0.0.1', $TargetPort)
        if (-not $Task.Wait(250)) { return $false }
        return $Client.Connected
    }
    catch { return $false }
    finally { $Client.Dispose() }
}

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Missing .venv. Install Python 3.12+, then run: py -3.12 -m venv .venv; .\.venv\Scripts\python.exe -m pip install -e '.[dev]'"
}

& $Python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw 'The project virtual environment must use Python 3.12 or newer.'
}

& $Python -c "import fastapi, uvicorn, jinja2, jsonschema, openpyxl"
if ($LASTEXITCODE -ne 0) {
    throw "Required packages are missing. Run: .\.venv\Scripts\python.exe -m pip install -e '.[dev]'"
}

if (Test-PortInUse -TargetPort $Port) {
    throw "Port $Port is already in use. Stop that process or run: .\scripts\start.ps1 -Port <another-port>"
}

try {
    Write-Host "Starting FFCS Studio at $Url"
    $Server = Start-Process -FilePath $Python -ArgumentList @(
        '-m', 'ffcs_studio', 'serve', '--host', '127.0.0.1', '--port', "$Port"
    ) -WorkingDirectory $ProjectRoot -NoNewWindow -PassThru

    $Ready = $false
    for ($Attempt = 0; $Attempt -lt 80; $Attempt++) {
        if ($Server.HasExited) {
            throw "FFCS Studio exited before becoming ready (exit code $($Server.ExitCode))."
        }
        try {
            $Health = Invoke-RestMethod -Uri "$Url/health" -TimeoutSec 1
            if ($Health.status -eq 'ready') {
                $Ready = $true
                break
            }
        }
        catch { Start-Sleep -Milliseconds 250 }
    }

    if (-not $Ready) {
        throw 'FFCS Studio did not become ready within 20 seconds.'
    }

    Write-Host 'Ready. Press Ctrl+C in this terminal to stop the server cleanly.'
    if (-not $NoBrowser) {
        Start-Process $Url
    }
    Wait-Process -Id $Server.Id
}
finally {
    if ($null -ne $Server -and -not $Server.HasExited) {
        Write-Host 'Waiting for FFCS Studio to stop cleanly...'
        if (-not $Server.WaitForExit(5000)) {
            Write-Warning 'The server did not stop within 5 seconds; ending the child process.'
            Stop-Process -Id $Server.Id
            $Server.WaitForExit(5000) | Out-Null
        }
    }
}
