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
        & $NSSM install $ServiceName $PythonExe $EntryScript --monitor --interval $Interval
    }
    & $NSSM set $ServiceName DisplayName $DisplayName
    & $NSSM set $ServiceName Description $Description
    & $NSSM set $ServiceName AppDirectory $ProjectRoot
    & $NSSM set $ServiceName Start SERVICE_AUTO_START

    # Logging
    $StdoutLog = Join-Path $LogDir "service_stdout.log"
    $StderrLog = Join-Path $LogDir "service_stderr.log"
    & $NSSM set $ServiceName AppStdout $StdoutLog
    & $NSSM set $ServiceName AppStderr $StderrLog
    & $NSSM set $ServiceName AppStdoutCreationDisposition 4  # Append
    & $NSSM set $ServiceName AppStderrCreationDisposition 4  # Append
    & $NSSM set $ServiceName AppRotateFiles 1
    & $NSSM set $ServiceName AppRotateBytes 10485760  # 10 MB

    # Crash recovery: restart after 10 seconds
    & $NSSM set $ServiceName AppRestartDelay 10000
    & $NSSM set $ServiceName AppExit Default Restart

    # Start the service
    & $NSSM start $ServiceName

    Write-Host ""
    Write-Host "Service '$DisplayName' installed and started." -ForegroundColor Green
    Write-Host "  Interval:  $Interval minutes" -ForegroundColor Gray
    Write-Host "  Log files: $LogDir" -ForegroundColor Gray
    Write-Host "  Manage:    services.msc or '$NSSM edit $ServiceName'" -ForegroundColor Gray
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
    & $NSSM remove $ServiceName confirm
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
