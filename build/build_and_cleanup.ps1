# build_and_cleanup.ps1
# Script autonome : installe les outils necessaires, build l'installateur,
# puis desinstalle tout ce qui a ete installe temporairement.
# A executer en PowerShell (clic droit > Executer avec PowerShell, ou depuis un terminal).

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoUrl = "https://github.com/Nistro-dev/Karting86-OCR.git"
$workDir = "$env:TEMP\ApexOCR_Build"
$installedPython = $false
$installedInnoSetup = $false
$installedGit = $false

function Write-Step($n, $total, $msg) {
    Write-Host "`n[$n/$total] $msg" -ForegroundColor Cyan
}

$totalSteps = 8

# ---- 1. Git ----
Write-Step 1 $totalSteps "Verification de Git..."
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "  Installation de Git..." -ForegroundColor Yellow
    winget install Git.Git -e --accept-source-agreements --accept-package-agreements | Out-Null
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    $installedGit = $true
} else {
    Write-Host "  Git deja present."
}

# ---- 2. Python ----
Write-Step 2 $totalSteps "Verification de Python..."
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Write-Host "  Installation de Python 3.12..." -ForegroundColor Yellow
    winget install Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements | Out-Null
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    $installedPython = $true
} else {
    Write-Host "  Python deja present."
}

# ---- 3. Inno Setup ----
Write-Step 3 $totalSteps "Verification de Inno Setup..."
$isccPaths = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$isccExe = $isccPaths | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $isccExe) {
    Write-Host "  Installation de Inno Setup..." -ForegroundColor Yellow
    winget install JRSoftware.InnoSetup -e --accept-source-agreements --accept-package-agreements | Out-Null
    $isccExe = $isccPaths | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $isccExe) {
        Write-Host "ERREUR: Inno Setup introuvable apres installation." -ForegroundColor Red
        exit 1
    }
    $installedInnoSetup = $true
} else {
    Write-Host "  Inno Setup deja present."
}

# ---- 4. Clone du repo ----
Write-Step 4 $totalSteps "Clone du depot..."
if (Test-Path $workDir) { Remove-Item $workDir -Recurse -Force }
git clone $repoUrl $workDir
Set-Location $workDir

# ---- 5. Dependances Python + PyInstaller ----
Write-Step 5 $totalSteps "Installation des dependances Python..."
py -m pip install --upgrade pip | Out-Null
py -m pip install -r requirements.txt pyinstaller | Out-Null

# ---- 6. Build exe ----
Write-Step 6 $totalSteps "Generation de l'icone et compilation de l'executable..."
py build\make_icon.py
py build\make_installer_branding.py
py -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name "ApexTimingOCR" `
    --icon "assets\icon.ico" `
    --collect-all customtkinter `
    --collect-all bleak `
    --collect-submodules winrt `
    --add-data "apex_ocr\ui\theme_newkart.json;apex_ocr\ui" `
    --add-data "assets\logo_favicon.png;assets" `
    --add-data "assets\logo_square.png;assets" `
    --add-data "assets\logo_round.png;assets" `
    main.py

# ---- 7. Build installateur ----
Write-Step 7 $totalSteps "Compilation de l'installateur (Inno Setup)..."
& $isccExe build\installer.iss

# Copier l'installateur sur le Bureau avant nettoyage
$installerSrc = "$workDir\dist_installer\ApexTimingOCR_Setup.exe"
$desktop = [Environment]::GetFolderPath("Desktop")
$installerDst = "$desktop\ApexTimingOCR_Setup.exe"
if (Test-Path $installerSrc) {
    Copy-Item $installerSrc $installerDst -Force
    Write-Host "`n  Installateur copie sur le Bureau : $installerDst" -ForegroundColor Green
} else {
    Write-Host "`n  ERREUR: installateur introuvable." -ForegroundColor Red
    exit 1
}

# ---- 8. Nettoyage ----
Write-Step 8 $totalSteps "Nettoyage..."

# Supprimer le dossier de build
Set-Location $env:TEMP
Remove-Item $workDir -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "  Dossier de build supprime."

# Desinstaller ce qu'on a installe
if ($installedPython) {
    Write-Host "  Desinstallation de Python..." -ForegroundColor Yellow
    winget uninstall Python.Python.3.12 --accept-source-agreements | Out-Null
}
if ($installedInnoSetup) {
    Write-Host "  Desinstallation de Inno Setup..." -ForegroundColor Yellow
    winget uninstall JRSoftware.InnoSetup --accept-source-agreements | Out-Null
}
if ($installedGit) {
    Write-Host "  Desinstallation de Git..." -ForegroundColor Yellow
    winget uninstall Git.Git --accept-source-agreements | Out-Null
}

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "  Termine !" -ForegroundColor Green
Write-Host "  Installateur : $installerDst" -ForegroundColor Green
Write-Host "  Tous les outils temporaires ont ete nettoyes." -ForegroundColor Green
Write-Host "========================================`n" -ForegroundColor Green
pause
