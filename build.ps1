<#
    Build AeroLab Studio end to end.

        .\build.ps1                 icon, tests, executable, installer, portable zip
        .\build.ps1 -SkipTests      skip the pytest run
        .\build.ps1 -SkipInstaller  stop after the executable

    Outputs land in .\dist:
        AeroLabStudio\                     the application folder
        AeroLabStudio-Setup-<version>.exe  the Windows installer
        AeroLabStudio-<version>-portable.zip
#>
param(
    [switch]$SkipTests,
    [switch]$SkipInstaller
)

# Native tools here write progress to stderr, which PowerShell turns into ErrorRecords.
# "Continue" keeps that from aborting the script, and every native call is checked with
# $LASTEXITCODE rather than $? — $? is false whenever anything reached stderr, even on a
# completely successful build.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

function Step($text) { Write-Host "`n=== $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`nFAILED: $text" -ForegroundColor Red; exit 1 }
function CheckExit($text) { if ($LASTEXITCODE -ne 0) { Fail $text } }

$version = (python -c "import sys; sys.path.insert(0,'.'); from aerolab import __version__; print(__version__)").Trim()
Write-Host "AeroLab Studio $version" -ForegroundColor Green

Step "Checking the build tools"
python -c "import PyInstaller" 2>$null
CheckExit "PyInstaller is missing. Run: pip install pyinstaller"

Step "Drawing the icon and version resource"
python build_assets\make_icon.py
CheckExit "the icon could not be generated"

if (-not $SkipTests) {
    Step "Running the test suite"
    python -m pytest tests -q
    CheckExit "tests failed - fix them before shipping a build"
}

Step "Building the executable"
if (Test-Path dist\AeroLabStudio) { Remove-Item dist\AeroLabStudio -Recurse -Force }
python -m PyInstaller AeroLabStudio.spec --noconfirm --distpath dist --workpath build
CheckExit "PyInstaller could not build the application"

Step "Self-testing the built application"
& dist\AeroLabStudio\AeroLabStudio.exe --selftest
CheckExit "the built application failed its own self-test"

Step "Packing the portable zip"
# Compress-Archive gives up quietly on a tree this size (1,200+ files, 270 MB), so the
# .NET API does the work; it also keeps the AeroLabStudio\ folder at the zip root.
$zip = Join-Path (Resolve-Path dist) "AeroLabStudio-$version-portable.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    (Resolve-Path dist\AeroLabStudio).Path, $zip,
    [System.IO.Compression.CompressionLevel]::Optimal, $true)
if (-not (Test-Path $zip)) { Fail "the portable zip was not created" }
Write-Host "  $zip  ($([math]::Round((Get-Item $zip).Length / 1MB, 1)) MB)"

if (-not $SkipInstaller) {
    Step "Compiling the installer"
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    $iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $iscc) {
        Write-Host "  Inno Setup not found - skipping the installer." -ForegroundColor Yellow
        Write-Host "  Install it with:  winget install JRSoftware.InnoSetup" -ForegroundColor Yellow
    } else {
        & $iscc installer\AeroLabStudio.iss | Select-Object -Last 3
        CheckExit "the installer could not be compiled"
    }
}

Step "Done"
Get-ChildItem dist -File | Select-Object Name, @{N = "Size"; E = { "$([math]::Round($_.Length / 1MB, 1)) MB" } } | Format-Table -AutoSize
