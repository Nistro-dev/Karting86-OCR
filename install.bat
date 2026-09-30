@echo off
chcp 65001 >nul
echo ========================================
echo   Installation New Kart - Panneau led (sources)
echo ========================================
echo.

echo [1/2] Installation de Python...
winget install Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
echo.

echo [2/2] Installation des dependances Python...
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
echo   (Le serveur Firebird d'Apex Timing doit etre present sur ce PC.)
echo ========================================
pause
