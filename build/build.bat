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
    echo [1/7] Installation de Python...
    winget install Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
) else (
    echo [1/7] Python deja present.
)

echo [2/7] Installation des dependances + PyInstaller...
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
py -m pip install pyinstaller

echo [3/7] Generation de l'icone et des images de l'installeur...
py build\make_icon.py
py build\make_installer_branding.py

echo [4/7] Compilation de l'executable (PyInstaller)...
py -m PyInstaller --noconfirm --clean --onefile --windowed --name "ApexTimingOCR" --icon "assets\icon.ico" --collect-all customtkinter --add-data "apex_ocr\ui\theme_newkart.json;apex_ocr\ui" --add-data "apex_ocr\led\rgb_template.bin;apex_ocr\led" --add-data "test_timer.html;." --add-data "assets\logo_favicon.png;assets" --add-data "assets\logo_square.png;assets" --add-data "assets\logo_round.png;assets" main.py
if errorlevel 1 (
    echo ERREUR : PyInstaller a echoue.
    pause
    exit /b 1
)

echo [5/7] Installeur Tesseract OCR (embarque dans l'installateur)...
powershell -NoProfile -ExecutionPolicy Bypass -File build\fetch_tesseract.ps1
if errorlevel 1 (
    echo ERREUR : installeur Tesseract indisponible, build arrete.
    pause
    exit /b 1
)

where ISCC >nul 2>nul
if errorlevel 1 (
    set "ISCC_EXE=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
    if not exist "%ISCC_EXE%" set "ISCC_EXE=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if not exist "%ISCC_EXE%" (
        echo [6/7] Inno Setup introuvable, installation...
        winget install JRSoftware.InnoSetup -e --accept-source-agreements --accept-package-agreements
        set "ISCC_EXE=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
    )
) else (
    set "ISCC_EXE=ISCC"
)

echo [7/7] Compilation de l'installeur (Inno Setup)...
"%ISCC_EXE%" build\installer.iss
if errorlevel 1 (
    echo ERREUR : Inno Setup a echoue.
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Termine ! Installeur pret :
echo   dist_installer\ApexTimingOCR_Setup.exe
echo ========================================
pause
