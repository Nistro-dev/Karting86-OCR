@echo off
py "%~dp0ocr_timer.py"
if errorlevel 1 (
    echo.
    echo Erreur. Verifiez que Python et les dependances sont installes.
    echo Lancez install.bat si besoin.
    pause
)
