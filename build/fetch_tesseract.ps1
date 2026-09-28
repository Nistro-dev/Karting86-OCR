# Télécharge (si absent) l'installeur Tesseract OCR UB-Mannheim 64 bits dans build\vendor,
# pour l'embarquer dans l'installateur (installer.iss). Appelé par build.bat et
# build_and_cleanup.ps1. Sort avec un code != 0 si le fichier n'est pas disponible.
$ErrorActionPreference = "Stop"
$Version = "5.4.0.20240606"
$Url = "https://github.com/UB-Mannheim/tesseract/releases/download/v$Version/tesseract-ocr-w64-setup-$Version.exe"
$MinSize = 40MB   # l'installeur fait ~50 Mo : en dessous, c'est une page d'erreur ou un fichier tronqué

$vendor = Join-Path $PSScriptRoot "vendor"
$out = Join-Path $vendor "tesseract-setup.exe"
New-Item -ItemType Directory -Force $vendor | Out-Null

if ((Test-Path $out) -and ((Get-Item $out).Length -ge $MinSize)) {
    Write-Host "  Tesseract $Version deja present : $out"
    exit 0
}

Write-Host "  Telechargement de Tesseract OCR $Version (~50 Mo)..."
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $Url -OutFile "$out.part" -UseBasicParsing
    if ((Get-Item "$out.part").Length -lt $MinSize) { throw "fichier trop petit (telechargement incomplet ?)" }
    Move-Item "$out.part" $out -Force
    Write-Host "  OK : $out ($([math]::Round((Get-Item $out).Length / 1MB)) Mo)"
} catch {
    Remove-Item "$out.part" -ErrorAction SilentlyContinue
    Write-Host "ERREUR : impossible de telecharger l'installeur Tesseract." -ForegroundColor Red
    Write-Host "  URL : $Url" -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  Sans lui, l'installateur ne peut pas etre construit (Tesseract y est embarque)." -ForegroundColor Red
    Write-Host "  Solution : telecharger le fichier a la main et le placer dans $out" -ForegroundColor Red
    exit 1
}
