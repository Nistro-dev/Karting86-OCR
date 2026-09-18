@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0\.."

echo ========================================
echo   Build Apex Timing OCR - exe + installeur
echo ========================================
echo.

where py >nul 2>nul
if errorlevel 1 (
    echo [1/5] Installation de Python...
    winget install Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
) else (
    echo [1/5] Python deja present.
)

echo [2/5] Installation des dependances + PyInstaller...
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
py -m pip install pyinstaller

echo [3/5] Generation de l'icone...
py build\make_icon.py

echo [4/5] Compilation de l'executable (PyInstaller)...
py -m PyInstaller --noconfirm --clean --onefile --windowed --name "ApexTimingOCR" --icon "assets\icon.ico" --collect-all customtkinter --add-data "apex_ocr\ui\theme_newkart.json;apex_ocr\ui" --add-data "assets\logo_newkart_poitiers.png;assets" main.py

where ISCC >nul 2>nul
if errorlevel 1 (
    set "ISCC_EXE=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
    if not exist "%ISCC_EXE%" set "ISCC_EXE=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if not exist "%ISCC_EXE%" (
        echo Inno Setup introuvable, installation...
        winget install JRSoftware.InnoSetup -e --accept-source-agreements --accept-package-agreements
        set "ISCC_EXE=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
    )
) else (
    set "ISCC_EXE=ISCC"
)

echo [5/5] Compilation de l'installeur (Inno Setup)...
"%ISCC_EXE%" build\installer.iss

echo.
echo ========================================
echo   Termine ! Installeur pret :
echo   dist_installer\ApexTimingOCR_Setup.exe
echo ========================================
pause
