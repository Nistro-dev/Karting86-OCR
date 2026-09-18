#define MyAppName "Apex Timing OCR"
#define MyAppVersion "1.0.0"
#define MyAppExeName "ApexTimingOCR.exe"
#define MyAppPublisher "Karting86"

[Setup]
AppId={{123CA05A-BE0C-4EF6-8DDD-814ED944A3D3}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={userpf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist_installer
OutputBaseFilename=ApexTimingOCR_Setup
SetupIconFile=..\assets\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"; Flags: unchecked
Name: "startup"; Description: "Lancer Apex Timing OCR au démarrage de Windows (réduit dans la zone de notification)"; GroupDescription: "Démarrage :"

[Files]
Source: "..\dist\ApexTimingOCR.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Désinstaller {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--minimized"; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
function TesseractInstalled(): Boolean;
begin
  Result := FileExists(ExpandConstant('{pf}\Tesseract-OCR\tesseract.exe'))
    or FileExists(ExpandConstant('{pf32}\Tesseract-OCR\tesseract.exe'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if (CurStep = ssPostInstall) and (not TesseractInstalled()) then
  begin
    WizardForm.StatusLabel.Caption := 'Installation de Tesseract OCR (moteur de reconnaissance de caractères)...';
    WizardForm.Update;
    Exec('winget',
      'install UB-Mannheim.TesseractOCR -e --silent --accept-source-agreements --accept-package-agreements',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;
