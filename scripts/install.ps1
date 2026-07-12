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
.PARAMETER AllowDowngrade
    Proceed even when the bundle is older than the installed version
    (db schema migrations are forward-only; downgrade is unsupported).
.PARAMETER Purge
    With -Action uninstall: also delete config\ and data\ (cache DB).
    Without it, both are preserved and a later reinstall picks them up.
.EXAMPLE
    .\install.ps1
    .\install.ps1 -Action uninstall
    .\install.ps1 -InstallRoot D:\illumio-ops
    .\install.ps1 -Action uninstall -InstallRoot D:\illumio-ops
#>
param(
    [ValidateSet("install", "uninstall")]
    [string]$Action = "install",
    [string]$InstallRoot = "C:\illumio-ops",
    [switch]$AllowDowngrade,
    [switch]$Purge
)

# Require elevation
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERROR: Run this script as Administrator." -ForegroundColor Red
    exit 1
}

$SRC = Split-Path -Parent $MyInvocation.MyCommand.Path

# ── Migration: C:\illumio_ops → C:\illumio-ops ────────────────────────────────
# Resolve nssm once: prefer the bundled deploy\nssm.exe (offline bundles ship it
# there and it is NOT on PATH on air-gapped hosts — same precedence as
# deploy\install_service.ps1), then fall back to PATH. Fail clearly if neither.
function Resolve-Nssm {
    $bundled = Join-Path $SRC "deploy\nssm.exe"
    if (Test-Path $bundled) { return $bundled }
    $cmd = Get-Command nssm -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    Write-Host "ERROR: NSSM not found (looked for $bundled, then PATH)." -ForegroundColor Red
    Write-Host "       The offline bundle ships nssm.exe under deploy\nssm.exe — re-extract the bundle if it is missing." -ForegroundColor Red
    exit 1
}

function Invoke-NssmSet {
    param([string[]]$NssmArgs)
    & $script:NSSM set @NssmArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: nssm set $NssmArgs failed (exit $LASTEXITCODE)" -ForegroundColor Red
        exit 1
    }
}

# Preserve operator-set service flags (e.g. a custom --interval) across the path
# migration: read the existing AppParameters and only swap the old root prefix
# for the new one, instead of overwriting with a fixed parameter string. Fall
# back to the default when the value cannot be read.
function Get-MigratedAppParameters {
    param([string]$OldRoot, [string]$NewRoot)
    $current = ((& $script:NSSM get IllumioOps AppParameters 2>$null) -join "").Trim()
    if ([string]::IsNullOrWhiteSpace($current)) {
        return "$NewRoot\illumio-ops.py --monitor --interval 10"
    }
    return $current.Replace($OldRoot, $NewRoot)
}

function Invoke-MigrateFromUnderscoreRoot {
    $OldRoot = "C:\illumio_ops"
    $NewRoot = "C:\illumio-ops"

    # ── Step 1: Partial-migration detection ───────────────────────────────────
    # OldRoot is gone but NewRoot exists without a MIGRATED_FROM marker.
    # This means the script was killed after Move-Item but before nssm/marker.
    if (-not (Test-Path $OldRoot)) {
        if ((Test-Path $NewRoot) -and -not (Test-Path "$NewRoot\MIGRATED_FROM")) {
            # No service and no OldRoot means this is NOT a torn migration —
            # e.g. a reinstall over a preserved config\/data\ after uninstall.
            # Writing MIGRATED_FROM here would fabricate a migration record.
            if (-not (Get-Service IllumioOps -ErrorAction SilentlyContinue)) { return }
            $script:NSSM = Resolve-Nssm
            # Fix I1: trim \r that nssm includes in its stdout on Windows
            $currentAppDir = ((& $script:NSSM get IllumioOps AppDirectory 2>$null) -join "").Trim()
            if ($currentAppDir -eq $OldRoot) {
                Write-Host "==> Detected partial migration: re-running nssm reconfiguration" -ForegroundColor Yellow
                # Fix I3: check exit code on every nssm set via helper
                Invoke-NssmSet IllumioOps,AppDirectory,$NewRoot
                Invoke-NssmSet IllumioOps,Application,"$NewRoot\python\python.exe"
                Invoke-NssmSet IllumioOps,AppParameters,(Get-MigratedAppParameters $OldRoot $NewRoot)
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

    # Resolve nssm before any irreversible mutation (Move-Item below) so a
    # missing nssm fails fast instead of leaving a half-migrated install.
    $script:NSSM = Resolve-Nssm

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
    Invoke-NssmSet IllumioOps,AppParameters,(Get-MigratedAppParameters $OldRoot $NewRoot)
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
    if ($Purge) {
        Write-Host "==> Removing $InstallRoot (-Purge: config and data (cache DB) will be deleted)" -ForegroundColor Yellow
        Remove-Item -Recurse -Force $InstallRoot -ErrorAction SilentlyContinue
    } else {
        Write-Host "==> Removing $InstallRoot (preserving config\ and data\)" -ForegroundColor Yellow
        Get-ChildItem $InstallRoot -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -notin @("config", "data") } |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "    Config preserved at: $InstallRoot\config\" -ForegroundColor Gray
        Write-Host "    Data preserved at:   $InstallRoot\data\  (cache DB; reinstall picks it up)" -ForegroundColor Gray
        Write-Host "    To fully remove:     .\install.ps1 -Action uninstall -Purge" -ForegroundColor Gray
    }
    Write-Host "==> Uninstall complete." -ForegroundColor Green
    exit 0
}

# ── Install / Upgrade ─────────────────────────────────────────────────────────
if ($InstallRoot -eq "C:\illumio-ops") {
    Invoke-MigrateFromUnderscoreRoot
}

$IsUpgrade = Test-Path (Join-Path $InstallRoot "config\config.json")

# ── Upgrade guards (parity with install.sh) ───────────────────────────────────
if ($IsUpgrade) {
    # Downgrade guard: db schema migrations are forward-only (PRAGMA
    # user_version); installing an older bundle over a newer install is
    # unsupported. Compare base versions (strip +hash dev suffix).
    $BundleBase = $null
    $versionFile = Join-Path $SRC "VERSION"
    if (Test-Path $versionFile) {
        $BundleBase = (Get-Content $versionFile -Raw).Trim().Split("+")[0]
    }
    $InstalledVersion = $null
    $initPy = Join-Path $InstallRoot "src\__init__.py"
    if (Test-Path $initPy) {
        $m = Select-String -Path $initPy -Pattern '^__version__\s*=\s*["'']([^"'']+)["'']'
        if ($m) { $InstalledVersion = $m.Matches[0].Groups[1].Value }
    }
    if ($InstalledVersion -and $BundleBase) {
        try {
            if ([version]$BundleBase -lt [version]$InstalledVersion) {
                if (-not $AllowDowngrade) {
                    Write-Host "ERROR: bundle version $BundleBase is older than installed $InstalledVersion." -ForegroundColor Red
                    Write-Host "       Downgrade is unsupported (db schema migrations are forward-only)." -ForegroundColor Red
                    Write-Host "       Re-run with -AllowDowngrade to proceed anyway." -ForegroundColor Red
                    exit 1
                }
                Write-Host "WARNING: downgrading $InstalledVersion -> $BundleBase (-AllowDowngrade given)." -ForegroundColor Yellow
            }
        } catch {
            # Unparseable version strings: skip the string comparison
            # (fails open, mirroring install.sh when sed finds no match).
        }
    }
    # Fallback downgrade guard: an uninstall (non-purge) deletes src\ but
    # keeps config\ + data\, so InstalledVersion above is unreadable on
    # reinstall. Detect a newer-than-bundle DB directly via PRAGMA
    # user_version vs the bundle schema.py migration ceiling.
    $DbFile = Join-Path $InstallRoot "data\pce_cache.sqlite"
    $BundlePy = Join-Path $SRC "python\python.exe"
    if (-not $InstalledVersion -and (Test-Path $DbFile) -and (Test-Path $BundlePy)) {
        $BundleMaxUv = $null
        $m2 = Select-String -Path (Join-Path $SRC "app\src\pce_cache\schema.py") -Pattern '^_MIGRATION_AGG_BUCKET_DAY = (\d+)' -ErrorAction SilentlyContinue
        if ($m2) { $BundleMaxUv = [int]$m2.Matches[0].Groups[1].Value }
        $DbUv = $null
        $out = & $BundlePy -c "import sqlite3,sys; print(sqlite3.connect(f'file:{sys.argv[1]}?mode=ro', uri=True).execute('PRAGMA user_version').fetchone()[0])" $DbFile 2>$null
        if ($LASTEXITCODE -eq 0 -and $out -match '^\d+$') { $DbUv = [int]$out }
        if ($null -ne $BundleMaxUv -and $null -ne $DbUv -and $DbUv -gt $BundleMaxUv) {
            if (-not $AllowDowngrade) {
                Write-Host "ERROR: existing cache DB user_version=$DbUv is newer than this bundle understands (max $BundleMaxUv)." -ForegroundColor Red
                Write-Host "       The DB was migrated by newer code; installing an older bundle over it is unsupported." -ForegroundColor Red
                Write-Host "       Re-run with -AllowDowngrade to proceed anyway." -ForegroundColor Red
                exit 1
            }
            Write-Host "WARNING: proceeding over newer cache DB (user_version=$DbUv > max $BundleMaxUv) (-AllowDowngrade given)." -ForegroundColor Yellow
        }
    }
    # Service guard: robocopy over a running service risks copying onto a
    # locked python.exe / torn state. Stop it; install_service.ps1 starts
    # the service again at the end of the install.
    $svcGuard = Get-Service IllumioOps -ErrorAction SilentlyContinue
    if ($svcGuard -and $svcGuard.Status -eq "Running") {
        Write-Host "==> Stopping running service for upgrade (re-registered and started at the end)" -ForegroundColor Yellow
        try {
            Stop-Service IllumioOps -ErrorAction Stop
            $svcGuard.WaitForStatus("Stopped", [TimeSpan]::FromSeconds(30))
        } catch {
            Write-Host "ERROR: failed to stop IllumioOps; stop it manually and re-run." -ForegroundColor Red
            exit 1
        }
    }
}

Write-Host "==> Installing to $InstallRoot  (upgrade=$IsUpgrade)" -ForegroundColor Cyan
New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
# Runtime dirs (parity with install.sh): sqlite creates the cache DB file
# but not its parent directory, so data\ must exist before first use.
foreach ($d in @("logs", "data", "reports")) {
    New-Item -ItemType Directory -Path (Join-Path $InstallRoot $d) -Force | Out-Null
}

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

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: pip install failed (exit $LASTEXITCODE) - installation is incomplete." -ForegroundColor Red
    exit 1
}

Write-Host "==> Verifying installed dependencies"
& "$InstallRoot\python\python.exe" "$InstallRoot\scripts\verify_deps.py" --offline-bundle
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: dependency verification failed - installation is incomplete." -ForegroundColor Red
    exit 1
}

Write-Host "==> Registering Windows service"
& "$SRC\deploy\install_service.ps1" -Action install -InstallRoot $InstallRoot

if ($IsUpgrade) {
    Write-Host "==> Upgrade complete. Restart: Restart-Service IllumioOps" -ForegroundColor Green
} else {
    Write-Host "==> Installation complete." -ForegroundColor Green
    Write-Host "    Edit config: notepad $InstallRoot\config\config.json" -ForegroundColor Gray
}
