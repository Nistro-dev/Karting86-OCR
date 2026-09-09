@echo off
chcp 65001 >nul
echo ========================================
echo   Installation Apex Timing OCR
echo ========================================
echo.

echo [1/3] Installation de Python...
winget install Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
echo.

echo [2/3] Installation de Tesseract OCR...
winget install UB-Mannheim.TesseractOCR -e --accept-source-agreements --accept-package-agreements
echo.

echo [3/3] Installation des dependances Python...
py -m pip install --upgrade pip
py -m pip install -r "%~dp0requirements.txt"

if errorlevel 1 (
    echo.
    echo *** Si erreur : fermez cette fenetre, rouvrez-la ***
    echo *** puis relancez install.bat                     ***
    echo.
)

echo.
echo ========================================
echo   Installation terminee !
echo   Lancez run.bat pour demarrer.
echo ========================================
pause
