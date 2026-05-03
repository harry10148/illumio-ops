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
