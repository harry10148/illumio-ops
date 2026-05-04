<#
.SYNOPSIS
    Install or uninstall the illumio_ops offline bundle on Windows.
.DESCRIPTION
    install  : Copies bundled Python + app, installs wheels, registers NSSM service.
               Safe to re-run for upgrades — config.json, alerts.json (rules),
               and rule_schedules.json preserved.
    uninstall: Stops and removes the NSSM service, then deletes the install directory.
.PARAMETER Action
    install (default) | uninstall
.PARAMETER InstallRoot
    Installation directory. Default: C:\illumio-ops
.EXAMPLE
    .\install.ps1
    .\install.ps1 -Action uninstall
    .\install.ps1 -InstallRoot D:\illumio-ops
    .\install.ps1 -Action uninstall -InstallRoot D:\illumio-ops
#>
param(
    [ValidateSet("install", "uninstall")]
    [string]$Action = "install",
    [string]$InstallRoot = "C:\illumio-ops"
)

# Require elevation
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERROR: Run this script as Administrator." -ForegroundColor Red
    exit 1
}

$SRC = Split-Path -Parent $MyInvocation.MyCommand.Path

# ── Migration: C:\illumio_ops → C:\illumio-ops ────────────────────────────────
function Invoke-NssmSet {
    param([string[]]$NssmArgs)
    & nssm set @NssmArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: nssm set $NssmArgs failed (exit $LASTEXITCODE)" -ForegroundColor Red
        exit 1
    }
}

function Invoke-MigrateFromUnderscoreRoot {
    $OldRoot = "C:\illumio_ops"
    $NewRoot = "C:\illumio-ops"

    # ── Step 1: Partial-migration detection ───────────────────────────────────
    # OldRoot is gone but NewRoot exists without a MIGRATED_FROM marker.
    # This means the script was killed after Move-Item but before nssm/marker.
    if (-not (Test-Path $OldRoot)) {
        if ((Test-Path $NewRoot) -and -not (Test-Path "$NewRoot\MIGRATED_FROM")) {
            # Fix I1: trim \r that nssm includes in its stdout on Windows
            $currentAppDir = ((& nssm get IllumioOps AppDirectory 2>$null) -join "").Trim()
            if ($currentAppDir -eq $OldRoot) {
                Write-Host "==> Detected partial migration: re-running nssm reconfiguration" -ForegroundColor Yellow
                # Fix I3: check exit code on every nssm set via helper
                Invoke-NssmSet IllumioOps,AppDirectory,$NewRoot
                Invoke-NssmSet IllumioOps,Application,"$NewRoot\python\python.exe"
                Invoke-NssmSet IllumioOps,AppParameters,"$NewRoot\illumio-ops.py --monitor --interval 10"
                Invoke-NssmSet IllumioOps,AppStdout,"$NewRoot\logs\service_stdout.log"
                Invoke-NssmSet IllumioOps,AppStderr,"$NewRoot\logs\service_stderr.log"
                Set-Content "$NewRoot\MIGRATED_FROM" $OldRoot
                Write-Host "==> Partial migration completed; $NewRoot\MIGRATED_FROM written." -ForegroundColor Green
                Write-Host "    NOTE: service was stopped for migration. Restart with 'Start-Service IllumioOps' after install.ps1 finishes." -ForegroundColor Yellow
            } else {
                # nssm already points at NewRoot — just the marker is missing
                Set-Content "$NewRoot\MIGRATED_FROM" $OldRoot
                Write-Host "==> Detected complete migration without marker; wrote marker." -ForegroundColor Yellow
                # Fix M1: add stopped-service warning consistent with the other two branches
                Write-Host "    NOTE: service was stopped for migration. Restart with 'Start-Service IllumioOps' after install.ps1 finishes." -ForegroundColor Yellow
            }
        }
        # OldRoot is gone; nothing left to migrate (or we just finished above)
        return
    }

    # ── Step 2: Already fully migrated ───────────────────────────────────────
    if ((Test-Path $NewRoot) -and (Test-Path "$NewRoot\MIGRATED_FROM")) { return }

    # ── Step 3: Dual-existence error ──────────────────────────────────────────
    if (Test-Path $NewRoot) {
        Write-Host "ERROR: Both $OldRoot and $NewRoot exist; manual cleanup required." -ForegroundColor Red
        exit 1
    }

    # ── Step 4: Pre-flight — NSSM service must be registered ─────────────────
    $svc = Get-Service IllumioOps -ErrorAction SilentlyContinue
    if (-not $svc) {
        Write-Host "ERROR: $OldRoot exists but IllumioOps service is not registered." -ForegroundColor Red
        Write-Host "       Manual cleanup required: rename or remove $OldRoot, then re-run." -ForegroundColor Red
        exit 1
    }

    # ── Step 5: Stop service with explicit failure handling ───────────────────
    if ($svc.Status -eq 'Running') {
        try {
            Stop-Service IllumioOps -ErrorAction Stop
            # Fix M2: wait for the process to fully exit before Move-Item touches the directory
            $svc.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(30))
        } catch {
            Write-Host "ERROR: Failed to stop IllumioOps service; cannot migrate while running." -ForegroundColor Red
            Write-Host "       Diagnose: Get-Service IllumioOps; Get-EventLog -LogName System -Source 'Service Control Manager' -Newest 5" -ForegroundColor Red
            exit 1
        }
    }

    # ── Step 6: Move directory ────────────────────────────────────────────────
    Write-Host "==> Migrating $OldRoot to $NewRoot" -ForegroundColor Cyan
    # Fix I2: fail fast on Move-Item errors (e.g. locked files)
    try {
        Move-Item $OldRoot $NewRoot -ErrorAction Stop
    } catch {
        Write-Host "ERROR: Failed to move $OldRoot to $NewRoot." -ForegroundColor Red
        Write-Host "       Cause: $_" -ForegroundColor Red
        Write-Host "       Common cause: file locked by another process. Diagnose with handle.exe." -ForegroundColor Red
        exit 1
    }

    # ── Step 7: Reconfigure NSSM ──────────────────────────────────────────────
    # Fix I3: check exit code on every nssm set via helper
    Invoke-NssmSet IllumioOps,AppDirectory,$NewRoot
    Invoke-NssmSet IllumioOps,Application,"$NewRoot\python\python.exe"
    Invoke-NssmSet IllumioOps,AppParameters,"$NewRoot\illumio-ops.py --monitor --interval 10"
    Invoke-NssmSet IllumioOps,AppStdout,"$NewRoot\logs\service_stdout.log"
    Invoke-NssmSet IllumioOps,AppStderr,"$NewRoot\logs\service_stderr.log"

    # ── Step 8: Write marker ──────────────────────────────────────────────────
    Set-Content "$NewRoot\MIGRATED_FROM" $OldRoot
    Write-Host "==> Migration complete; $NewRoot\MIGRATED_FROM records source path." -ForegroundColor Green

    # ── Step 9: Warn that service is left stopped ─────────────────────────────
    Write-Host "    NOTE: service was stopped for migration. Restart with 'Start-Service IllumioOps' after install.ps1 finishes." -ForegroundColor Yellow
}

# ── Uninstall ─────────────────────────────────────────────────────────────────
if ($Action -eq "uninstall") {
    Write-Host "==> Removing NSSM service" -ForegroundColor Yellow
    & "$SRC\deploy\install_service.ps1" -Action uninstall -InstallRoot $InstallRoot
    Write-Host "==> Removing $InstallRoot" -ForegroundColor Yellow
    Remove-Item -Recurse -Force $InstallRoot -ErrorAction SilentlyContinue
    Write-Host "==> Uninstall complete." -ForegroundColor Green
    exit 0
}

# ── Install / Upgrade ─────────────────────────────────────────────────────────
if ($InstallRoot -eq "C:\illumio-ops") {
    Invoke-MigrateFromUnderscoreRoot
}

$IsUpgrade = Test-Path (Join-Path $InstallRoot "config\config.json")

Write-Host "==> Installing to $InstallRoot  (upgrade=$IsUpgrade)" -ForegroundColor Cyan
New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null

Write-Host "==> Copying Python runtime"
Robocopy "$SRC\python" "$InstallRoot\python" /E /NP /NFL /NDL | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Host "ERROR: Robocopy failed copying Python runtime (exit $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}

Write-Host "==> Copying application files"
if ($IsUpgrade) {
    # Preserve operator-owned files on upgrade
    Robocopy "$SRC\app" "$InstallRoot" /E /NP /NFL /NDL `
        /XF "config.json" "alerts.json" "rule_schedules.json" | Out-Null
    if ($LASTEXITCODE -ge 8) {
        Write-Host "ERROR: Robocopy failed copying application files (exit $LASTEXITCODE)" -ForegroundColor Red
        exit 1
    }
} else {
    Robocopy "$SRC\app" "$InstallRoot" /E /NP /NFL /NDL | Out-Null
    if ($LASTEXITCODE -ge 8) {
        Write-Host "ERROR: Robocopy failed copying application files (exit $LASTEXITCODE)" -ForegroundColor Red
        exit 1
    }
    Copy-Item "$InstallRoot\config\config.json.example" `
              "$InstallRoot\config\config.json" -Force
}

Write-Host "==> Installing Python packages (offline)"
& "$InstallRoot\python\python.exe" -m pip install `
    --no-index `
    --find-links "$SRC\wheels" `
    -r "$InstallRoot\requirements-offline.txt" `
    --quiet

Write-Host "==> Registering Windows service"
& "$SRC\deploy\install_service.ps1" -Action install -InstallRoot $InstallRoot

if ($IsUpgrade) {
    Write-Host "==> Upgrade complete. Restart: Restart-Service IllumioOps" -ForegroundColor Green
} else {
    Write-Host "==> Installation complete." -ForegroundColor Green
    Write-Host "    Edit config: notepad $InstallRoot\config\config.json" -ForegroundColor Gray
}
