<#
.SYNOPSIS
    Install/Uninstall Illumio PCE Ops as a Windows Service using NSSM.

.DESCRIPTION
    This script uses NSSM (Non-Sucking Service Manager) to register the
    Illumio PCE Ops as a Windows service with auto-start and crash recovery.

.PARAMETER Action
    install   - Install and start the service
    uninstall - Stop and remove the service
    status    - Show the service status

.PARAMETER NssmPath
    Optional. Full path to nssm.exe if it is not in your system PATH.
    Example: -NssmPath "C:\Tools\nssm\nssm.exe"

.PARAMETER Interval
    Optional. Monitoring interval in minutes. Default: 10

.EXAMPLE
    .\install_service.ps1 -Action install
    .\install_service.ps1 -Action install -NssmPath "C:\Tools\nssm.exe"
    .\install_service.ps1 -Action install -NssmPath "C:\Tools\nssm.exe" -Interval 5
    .\install_service.ps1 -Action uninstall
    .\install_service.ps1 -Action status
#>

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("install", "uninstall", "status")]
    [string]$Action,

    [Parameter(Mandatory = $false)]
    [string]$NssmPath = "",

    [Parameter(Mandatory = $false)]
    [int]$Interval = 10,

    [Parameter(Mandatory = $false)]
    [string]$InstallRoot = ""
)

# ─── Configuration ────────────────────────────────────────────────────────────
$ServiceName = "IllumioOps"
$DisplayName = "Illumio PCE Ops"
$Description = "Monitors Illumio PCE for events, traffic anomalies, and health."
$ProjectRoot = Split-Path -Parent $PSScriptRoot          # deploy/ -> project root
if ($InstallRoot -ne "") { $ProjectRoot = $InstallRoot }
$EntryScript = Join-Path $ProjectRoot "illumio-ops.py"
$LogDir      = Join-Path $ProjectRoot "logs"

# Python priority: 1) bundled PBS  2) venv  3) system
$BundledPython = Join-Path $ProjectRoot "python\python.exe"
$VenvPython    = Join-Path $ProjectRoot "venv\Scripts\python.exe"
if (Test-Path $BundledPython) {
    $PythonExe = $BundledPython
    Write-Host "Using bundled Python: $PythonExe" -ForegroundColor Gray
} elseif (Test-Path $VenvPython) {
    $PythonExe = $VenvPython
    Write-Host "Using venv Python: $PythonExe" -ForegroundColor Gray
} else {
    $PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $PythonExe) {
        Write-Host "ERROR: Python not found." -ForegroundColor Red
        exit 1
    }
}

# ─── Resolve NSSM ─────────────────────────────────────────────────────────────
if ($NssmPath -and (Test-Path $NssmPath)) {
    $NSSM = $NssmPath
}
elseif (Test-Path (Join-Path $PSScriptRoot "nssm.exe")) {
    $NSSM = Join-Path $PSScriptRoot "nssm.exe"
}
else {
    $NssmCmd = Get-Command nssm -ErrorAction SilentlyContinue
    if ($NssmCmd) {
        $NSSM = $NssmCmd.Source
    }
    else {
        Write-Host "ERROR: NSSM not found." -ForegroundColor Red
        Write-Host "  The offline bundle ships nssm.exe under deploy\nssm.exe — re-extract"
        Write-Host "  the bundle if it is missing, or use -NssmPath to point at another copy."
        Write-Host "  Example:  .\install_service.ps1 -Action install -NssmPath 'C:\Tools\nssm.exe'"
        exit 1
    }
}

Write-Host "Using NSSM:   $NSSM" -ForegroundColor Gray
Write-Host "Using Python: $PythonExe" -ForegroundColor Gray
Write-Host "Project root: $ProjectRoot" -ForegroundColor Gray

# ─── NSSM helpers ─────────────────────────────────────────────────────────────
# nssm 失敗時只寫 stderr 並回非零 exit code，不會丟 PowerShell 例外。不檢查的話，
# 半套設定的服務（例如 AppDirectory 沒設成功）仍會被宣告成安裝成功，操作者要等到
# 服務起不來才發現。註冊/設定類失敗一律中止，讓上層 install.ps1 收到非零 exit code。
function Invoke-Nssm {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$What
    )
    & $NSSM @Arguments
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: $What failed (nssm exit $LASTEXITCODE)" -ForegroundColor Red
        exit 1
    }
}

function Invoke-NssmSet {
    param(
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][string[]]$Value
    )
    Invoke-Nssm -Arguments (@("set", $ServiceName, $Key) + $Value) -What "nssm set $Key"
}

# ─── Install ──────────────────────────────────────────────────────────────────
function Install-Service {
    Write-Host "`nInstalling $DisplayName..." -ForegroundColor Cyan

    # Create log directory
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }

    # Install the service (idempotent — skip if already registered)
    $existingSvc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($existingSvc) {
        Write-Host "  Service $ServiceName already registered — skipping nssm install" -ForegroundColor Gray
    } else {
        Invoke-Nssm -Arguments @("install", $ServiceName, $PythonExe, $EntryScript,
                                 "--monitor-gui", "--interval", "$Interval") -What "nssm install"
    }
    Invoke-NssmSet DisplayName $DisplayName
    Invoke-NssmSet Description $Description
    Invoke-NssmSet AppDirectory $ProjectRoot
    Invoke-NssmSet Start SERVICE_AUTO_START

    # Logging
    $StdoutLog = Join-Path $LogDir "service_stdout.log"
    $StderrLog = Join-Path $LogDir "service_stderr.log"
    Invoke-NssmSet AppStdout $StdoutLog
    Invoke-NssmSet AppStderr $StderrLog
    Invoke-NssmSet AppStdoutCreationDisposition 4  # Append
    Invoke-NssmSet AppStderrCreationDisposition 4  # Append
    Invoke-NssmSet AppRotateFiles 1
    Invoke-NssmSet AppRotateBytes 10485760  # 10 MB

    # Crash recovery: restart after 10 seconds
    Invoke-NssmSet AppRestartDelay 10000
    Invoke-NssmSet AppExit @("Default", "Restart")

    # Start the service.
    # 啟動失敗不中止安裝：全新安裝在 config\config.json 填入 PCE 憑證前本來就起不
    # 來，install.ps1 也把「已註冊但未 Running」當成警告而非錯誤。但成功橫幅不得
    # 無條件宣告 started——以 SCM 觀察到的實際狀態為準，否則半死的服務會被報成功。
    & $NSSM start $ServiceName
    $startExit = $LASTEXITCODE

    $svc = $null
    $deadline = (Get-Date).AddSeconds(30)
    do {
        Start-Sleep -Seconds 1
        $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    } while ($svc -and $svc.Status -ne "Running" -and (Get-Date) -lt $deadline)

    Write-Host ""
    if ($svc -and $svc.Status -eq "Running") {
        Write-Host "Service '$DisplayName' installed and started." -ForegroundColor Green
    } else {
        $observed = "not registered"
        if ($svc) { $observed = $svc.Status }
        Write-Host "Service '$DisplayName' installed but NOT running (status=$observed, nssm start exit $startExit)." -ForegroundColor Yellow
        Write-Host "  On a fresh install this is expected until config\config.json holds PCE credentials." -ForegroundColor Yellow
        Write-Host "  Otherwise check the log files below, then: Start-Service $ServiceName" -ForegroundColor Yellow
    }
    Write-Host "  Interval:  $Interval minutes" -ForegroundColor Gray
    Write-Host "  Log files: $LogDir" -ForegroundColor Gray
    Write-Host "  Manage:    services.msc or '$NSSM edit $ServiceName'" -ForegroundColor Gray

    # $LASTEXITCODE 仍留著上面 `nssm start` 的值，呼叫端（install.ps1）用它判斷
    # 「服務註冊是否成功」。註冊與設定都已逐項檢查過，走到這裡就是註冊成功，
    # 明確回 0；服務沒起來由呼叫端自己 Get-Service 判定並警告，不算註冊失敗。
    exit 0
}

# ─── Uninstall ────────────────────────────────────────────────────────────────
function Uninstall-Service {
    Write-Host "Stopping and removing $DisplayName..." -ForegroundColor Yellow
    $existingSvc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $existingSvc) {
        Write-Host "  Service $ServiceName not found — nothing to remove" -ForegroundColor Gray
        return
    }
    & $NSSM stop $ServiceName 2>$null
    # 同上：remove 失敗仍印「Service removed.」會讓操作者以為已清乾淨。
    Invoke-Nssm -Arguments @("remove", $ServiceName, "confirm") -What "nssm remove"
    Write-Host "Service removed." -ForegroundColor Green
}

# ─── Status ───────────────────────────────────────────────────────────────────
function Show-Status {
    & $NSSM status $ServiceName
}

# ─── Execute ──────────────────────────────────────────────────────────────────
switch ($Action) {
    "install" { Install-Service }
    "uninstall" { Uninstall-Service }
    "status" { Show-Status }
}
