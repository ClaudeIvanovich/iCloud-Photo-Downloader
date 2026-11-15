<#
.SYNOPSIS
  Builds iCloud Photo Downloader: venv, dependencies, tests, exe (PyInstaller), installer (Inno Setup).

.EXAMPLE
  .\build.ps1                  # everything; result: dist\iCloudPhotoDownloader-Setup-<version>.exe
  .\build.ps1 -SkipTests       # faster rebuild
  .\build.ps1 -SkipInstaller   # only dist\iCloudPhotoDownloader\ (no Inno Setup needed)
#>
param(
    [switch]$SkipTests,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Step($text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }
function Fail($text) { Write-Host "ERROR: $text" -ForegroundColor Red; exit 1 }
function Run($exe, [string[]]$arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { Fail "$exe $($arguments -join ' ') exited with code $LASTEXITCODE" }
}

# ---------------------------------------------------------------- tools
Step "Checking tools"

$python = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    $found = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $found) { $python = $found.Trim() }
}
if (-not $python) {
    Fail "Python 3.12 not found. Install it:  winget install --id Python.Python.3.12 -e"
}
Write-Host "Python 3.12: $python"

$iscc = $null
if (-not $SkipInstaller) {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    $onPath = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($onPath) { $candidates = @($onPath.Source) + $candidates }
    $iscc = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
    if (-not $iscc) {
        Fail ("Inno Setup 6 not found. Install it:  winget install --id JRSoftware.InnoSetup -e`n" +
              "       or build without the installer:  .\build.ps1 -SkipInstaller")
    }
    Write-Host "Inno Setup:  $iscc"
}

# ----------------------------------------------------------- environment
Step "Virtual environment and dependencies"

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    Run $python @("-m", "venv", ".venv")
}
# A venv made by `uv venv` has no pip; add it rather than demand a particular tool.
& $venvPython -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('pip') else 1)"
if ($LASTEXITCODE -ne 0) {
    Run $venvPython @("-m", "ensurepip", "--upgrade")
}
Run $venvPython @("-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", "requirements-dev.txt", "-e", ".")

$version = (& $venvPython -c "import ipd_app; print(ipd_app.__version__)").Trim()
if (-not $version) { Fail "Could not read the version from ipd_app.__version__" }
Write-Host "Version: $version"

# ----------------------------------------------------------------- tests
if (-not $SkipTests) {
    Step "Tests"
    $env:QT_QPA_PLATFORM = "offscreen"
    Run $venvPython @("-m", "pytest", "-q")
    Remove-Item Env:QT_QPA_PLATFORM
}

# ------------------------------------------------------------------- exe
Step "Icon and version resource"
Run $venvPython @("packaging\make_assets.py")

Step "PyInstaller"
$distExe = Join-Path $PSScriptRoot "dist\iCloudPhotoDownloader\iCloudPhotoDownloader.exe"
$running = Get-Process -Name iCloudPhotoDownloader -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $distExe }
if ($running) {
    Fail ("The program from dist\ is running (it may be in the tray) and locks its files.`n" +
          "       Close it with 'Выход' in the tray menu and run the build again.")
}
Run $venvPython @("-m", "PyInstaller", "packaging\app.spec", "--noconfirm", "--log-level", "WARN",
                  "--distpath", "dist", "--workpath", "build\pyinstaller")
$exe = Join-Path $PSScriptRoot "dist\iCloudPhotoDownloader\iCloudPhotoDownloader.exe"
if (-not (Test-Path -LiteralPath $exe)) { Fail "PyInstaller did not produce $exe" }

Step "Self-check of the packaged exe"
$report = Join-Path $PSScriptRoot "build\selfcheck.txt"
if (Test-Path -LiteralPath $report) { Remove-Item -LiteralPath $report }
$check = Start-Process -FilePath $exe -ArgumentList @("selfcheck", "`"$report`"") -Wait -PassThru
if (Test-Path -LiteralPath $report) { Get-Content -LiteralPath $report -Encoding UTF8 | Where-Object { $_ -match "^(OK|FAIL|RESULT)" } }
if ($check.ExitCode -ne 0) { Fail "The packaged exe failed its self-check, see $report" }

# ----------------------------------------------------------------- audit
# The installer packs exactly this folder. Nothing of the person who builds it
# (Apple ID, user name, paths, sessions, passwords) may be inside.
Step "Privacy audit of the program folder"
Run $venvPython @("packaging\audit_bundle.py", "dist\iCloudPhotoDownloader")

# ------------------------------------------------------------- installer
if ($SkipInstaller) {
    Step "Done (installer skipped)"
    Write-Host "Program folder: dist\iCloudPhotoDownloader\"
    exit 0
}

Step "Inno Setup"
Run $iscc @("/Qp", "/DAppVersion=$version", "packaging\installer.iss")
$setup = Join-Path $PSScriptRoot "dist\iCloudPhotoDownloader-Setup-$version.exe"
if (-not (Test-Path -LiteralPath $setup)) { Fail "Inno Setup did not produce $setup" }

Step "Done"
$sizeMb = [math]::Round((Get-Item -LiteralPath $setup).Length / 1MB, 1)
Write-Host "Installer: $setup ($sizeMb MB)"
