<#
.SYNOPSIS
    Pre-install environment check for illumio_ops offline bundle (Windows).
.DESCRIPTION
    Run BEFORE install.ps1 to validate the target host.
    Exit 0 = all PASS/WARN only.  Exit 1 = at least one FAIL.
.EXAMPLE
    .\preflight.ps1
#>

$BundleDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$FailCount = 0

function Pass { param($msg) Write-Host "  PASS  $msg" -ForegroundColor Green }
function Warn { param($msg) Write-Host "  WARN  $msg" -ForegroundColor Yellow }
function Fail { param($msg) Write-Host "  FAIL  $msg" -ForegroundColor Red; $script:FailCount++ }

Write-Host "illumio-ops pre-install check"
Write-Host "=============================="

# 1. OS version (Win10 / Server 2019+)
$osVer = [System.Environment]::OSVersion.Version
$caption = (Get-CimInstance Win32_OperatingSystem).Caption
if ($osVer.Major -ge 10) { Pass "OS: $caption" }
else { Fail "OS: $caption — Windows 10 / Server 2019 or newer required" }

# 2. Architecture
$arch = $env:PROCESSOR_ARCHITECTURE
if ($arch -eq "AMD64") { Pass "Architecture: $arch" }
else { Fail "Architecture: $arch — bundle requires AMD64 (x86_64)" }

# 3. PowerShell >= 5.1
$psVer = $PSVersionTable.PSVersion
if ($psVer.Major -gt 5 -or ($psVer.Major -eq 5 -and $psVer.Minor -ge 1)) {
    Pass "PowerShell: $($psVer.ToString())"
} else {
    Fail "PowerShell: $($psVer.ToString()) — requires 5.1+"
}

# 4. Administrator (WARN only)
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) { Pass "Running as Administrator" }
else { Warn "Not running as Administrator — install.ps1 requires elevation" }

# 5. NSSM
$nssmCmd    = Get-Command nssm.exe -ErrorAction SilentlyContinue
$nssmBundle = Join-Path $BundleDir "deploy\nssm.exe"
if ($nssmCmd) { Pass "NSSM: found at $($nssmCmd.Source)" }
elseif (Test-Path $nssmBundle) { Pass "NSSM: found in bundle at $nssmBundle" }
else { Fail "NSSM: not found — bundle should ship deploy\nssm.exe; re-extract the bundle or place nssm.exe in PATH" }

# 6. Disk space >= 500 MB on C:\
$drive = (Get-PSDrive C -ErrorAction SilentlyContinue)
if ($drive -and $drive.Free -ge 524288000) {
    Pass "Disk on C:\: $([int]($drive.Free / 1MB)) MB available (>= 500 MB required)"
} elseif ($drive) {
    Fail "Disk on C:\: $([int]($drive.Free / 1MB)) MB — need >= 500 MB"
} else {
    Warn "Disk space: unable to determine"
}

# 7. Bundle integrity
$versionFile = Join-Path $BundleDir "VERSION"
if (Test-Path $versionFile) { Pass "Bundle VERSION: $((Get-Content $versionFile -Raw).Trim())" }
else { Fail "Bundle VERSION file missing — bundle may be corrupt" }

foreach ($dir in @("python", "wheels", "app", "deploy")) {
    $p = Join-Path $BundleDir $dir
    if (Test-Path $p) { Pass "Bundle dir: $dir\" }
    else { Fail "Bundle dir missing: $dir\ — bundle may be corrupt" }
}

$wheelCount = (Get-ChildItem (Join-Path $BundleDir "wheels") -Filter "*.whl" -ErrorAction SilentlyContinue | Measure-Object).Count
if ($wheelCount -ge 20) { Pass "Wheels: $wheelCount .whl files (>= 20 required)" }
else { Fail "Wheels: only $wheelCount .whl files — expected >= 20" }

$bundledPython = Join-Path $BundleDir "python\python.exe"
if (Test-Path $bundledPython) {
    $pyVer = & $bundledPython --version 2>&1
    Pass "Bundled Python: $pyVer"
} else {
    Fail "Bundled Python not found: $bundledPython"
}

# 8. Upgrade detection
$installRoot = "C:\illumio-ops"
if (Test-Path (Join-Path $installRoot "config\config.json")) {
    Warn "Existing installation at $installRoot — this is an UPGRADE"
    Warn "config.json and rule_schedules.json will be preserved"
} else {
    Pass "No existing installation at $installRoot — fresh install"
}

Write-Host ""
Write-Host "=============================="
if ($FailCount -gt 0) {
    Write-Host "PREFLIGHT FAILED: $FailCount check(s) failed. Resolve before installing." -ForegroundColor Red
    exit 1
} else {
    Write-Host "PREFLIGHT PASSED: Host is ready for installation." -ForegroundColor Green
    exit 0
}
