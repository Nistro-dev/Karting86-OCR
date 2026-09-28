#define MyAppName "Apex Timing OCR"
#define MyAppVersion "2.6.0"
#define MyAppExeName "ApexTimingOCR.exe"
#define MyAppPublisher "CodeForgeStudio"
#define MyAppPublisherURL "https://codeforgestudio.fr"
#define TaskName "ApexTimingOCR"

; Tesseract OCR (UB-Mannheim) est embarqué dans l'installateur : vendor\tesseract-setup.exe
; est téléchargé par build.bat / build_and_cleanup.ps1 avant la compilation.
; Il s'installe dans Program Files (son installeur NSIS exige l'élévation : une seule
; invite UAC, uniquement si Tesseract est absent). L'appli reste installée par utilisateur.

[Setup]
AppId={{123CA05A-BE0C-4EF6-8DDD-814ED944A3D3}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppPublisherURL}
DefaultDirName={userpf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist_installer
OutputBaseFilename=ApexTimingOCR_Setup
SetupIconFile=..\assets\icon.ico
WizardImageFile=installer_assets\wizard_image.bmp
WizardSmallImageFile=installer_assets\wizard_small.bmp
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"; Flags: unchecked
Name: "startup"; Description: "Lancer Apex Timing OCR à l'ouverture de session et le relancer automatiquement s'il s'arrête (tâche planifiée)"; GroupDescription: "Démarrage :"

[Files]
Source: "..\dist\ApexTimingOCR.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\test_timer.html"; DestDir: "{app}"; Flags: ignoreversion
Source: "startup_task.xml"; DestDir: "{app}"; Flags: ignoreversion
; Installeur Tesseract embarqué, extrait dans {tmp} et supprimé après l'installation
Source: "vendor\tesseract-setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[InstallDelete]
; Ancien raccourci de démarrage (versions <= 2.5.3) : remplacé par la tâche planifiée
Type: files; Name: "{userstartup}\{#MyAppName}.lnk"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Page de test du chrono"; Filename: "{app}\test_timer.html"
Name: "{group}\Désinstaller {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "schtasks.exe"; Parameters: "/Delete /TN ""{#TaskName}"" /F"; Flags: runhidden; RunOnceId: "DelTask"

[Code]
const
  TesseractUrl = 'https://github.com/UB-Mannheim/tesseract/releases';

function TesseractExe(): String;
begin
  Result := ExpandConstant('{pf}\Tesseract-OCR\tesseract.exe');
  if not FileExists(Result) then
    Result := ExpandConstant('{pf32}\Tesseract-OCR\tesseract.exe');
end;

function TesseractInstalled(): Boolean;
begin
  Result := FileExists(TesseractExe());
end;

{ Installe Tesseract en silencieux depuis l'installeur embarqué. Son installeur NSIS
  exige l'élévation : ShellExec déclenche l'invite UAC (Exec échouerait avec le code 740). }
procedure InstallTesseract();
var
  SetupPath: String;
  ResultCode: Integer;
  Ok: Boolean;
begin
  SetupPath := ExpandConstant('{tmp}\tesseract-setup.exe');
  WizardForm.StatusLabel.Caption := 'Installation de Tesseract OCR (moteur de reconnaissance de caractères)...';
  WizardForm.Update;
  Ok := ShellExec('', SetupPath, '/S', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if Ok and (ResultCode = 0) and TesseractInstalled() then
    Log('Tesseract installé : ' + TesseractExe())
  else
  begin
    Log(Format('Installation de Tesseract échouée (ShellExec=%d, code=%d)', [Integer(Ok), ResultCode]));
    MsgBox('Tesseract OCR n''a pas pu être installé automatiquement (code ' + IntToStr(ResultCode) + ').' + #13#10#13#10
      + 'Sans lui, l''application ne peut pas lire le chrono.' + #13#10
      + 'Installez-le à la main (installeur Windows 64 bits, dossier par défaut C:\Program Files\Tesseract-OCR) :' + #13#10
      + TesseractUrl + #13#10#13#10
      + 'Une copie de l''installeur se trouve ici jusqu''à la fin de cette installation :' + #13#10 + SetupPath,
      mbError, MB_OK);
  end;
end;

{ Tâche planifiée : lancement à l'ouverture de session + relance automatique si le
  processus s'arrête (RestartOnFailure). Créée pour l'utilisateur courant, sans élévation.
  schtasks n'accepte le XML qu'en UTF-16 : la substitution des %%...%% du modèle et
  l'écriture en UTF-16 sont confiées à PowerShell (présent sur tout Windows). }
function PsQuote(const S: String): String;
begin
  Result := S;
  StringChangeEx(Result, '''', '''''', True);
  Result := '''' + Result + '''';
end;

procedure CreateStartupTask();
var
  Template, XmlPath, Cmd: String;
  ResultCode: Integer;
begin
  Template := ExpandConstant('{app}\startup_task.xml');
  XmlPath := ExpandConstant('{tmp}\ApexTimingOCR_task.xml');
  Cmd := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "'
    + '$x = [IO.File]::ReadAllText(' + PsQuote(Template) + ', [Text.Encoding]::UTF8); '
    + '$x = $x.Replace(''%%USERID%%'', $env:USERDOMAIN + ''\'' + $env:USERNAME)'
    + '.Replace(''%%APPEXE%%'', ' + PsQuote(ExpandConstant('{app}\{#MyAppExeName}')) + ')'
    + '.Replace(''%%APPDIR%%'', ' + PsQuote(ExpandConstant('{app}')) + '); '
    + '[IO.File]::WriteAllText(' + PsQuote(XmlPath) + ', $x, [Text.Encoding]::Unicode); '
    + 'schtasks.exe /Create /TN ''{#TaskName}'' /XML ' + PsQuote(XmlPath) + ' /F | Out-Null; '
    + 'exit $LASTEXITCODE"';
  if Exec('powershell.exe', Cmd, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
    Log('Tâche planifiée {#TaskName} créée')
  else
  begin
    Log(Format('Création de la tâche planifiée échouée (code %d)', [ResultCode]));
    MsgBox('La tâche planifiée de démarrage automatique n''a pas pu être créée (code ' + IntToStr(ResultCode) + ').' + #13#10
      + 'L''application fonctionne, mais il faudra la lancer à la main après chaque ouverture de session.',
      mbInformation, MB_OK);
  end;
  DeleteFile(XmlPath);
end;

procedure DeleteStartupTask();
var
  ResultCode: Integer;
begin
  Exec('schtasks.exe', '/Delete /TN "{#TaskName}" /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if not TesseractInstalled() then
      InstallTesseract();
    if WizardIsTaskSelected('startup') then
      CreateStartupTask()
    else
      DeleteStartupTask();  { l'utilisateur a décoché : ne pas garder une tâche d'une version précédente }
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\ApexTimingOCR');
    if DirExists(DataDir) then
    begin
      if MsgBox('Supprimer aussi la configuration et les journaux enregistrés (' + DataDir + ') ?',
        mbConfirmation, MB_YESNO) = IDYES then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
