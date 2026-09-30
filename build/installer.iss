#define MyAppName "New Kart - Panneau led"
#define MyAppVersion "3.0.0"
#define MyAppExeName "NewKartPanneauLed.exe"
#define MyAppPublisher "CodeForgeStudio"
#define MyAppPublisherURL "https://codeforgestudio.fr"
#define TaskName "NewKartPanneauLed"
#define LegacyTaskName "ApexTimingOCR"

; L'appli lit la base Firebird de GoKarts (Apex Timing) sur le PC de chrono : rien d'autre à
; installer (le serveur Firebird et son fbclient.dll 64 bits sont ceux d'Apex Timing).

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
OutputBaseFilename=NewKartPanneauLed_Setup
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
Name: "startup"; Description: "Lancer {#MyAppName} à l'ouverture de session et le relancer automatiquement s'il s'arrête (tâche planifiée)"; GroupDescription: "Démarrage :"

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "startup_task.xml"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; Versions <= 2.x (« Apex Timing OCR ») : exe, page de test et raccourci de démarrage
Type: files; Name: "{app}\ApexTimingOCR.exe"
Type: files; Name: "{app}\test_timer.html"
Type: files; Name: "{userstartup}\Apex Timing OCR.lnk"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Désinstaller {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "schtasks.exe"; Parameters: "/Delete /TN ""{#TaskName}"" /F"; Flags: runhidden; RunOnceId: "DelTask"

[Code]
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
  XmlPath := ExpandConstant('{tmp}\NewKartPanneauLed_task.xml');
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

{ La tâche des versions <= 2.x relancerait un exe qui n'existe plus : toujours supprimée. }
procedure DeleteLegacyStartupTask();
var
  ResultCode: Integer;
begin
  Exec('schtasks.exe', '/Delete /TN "{#LegacyTaskName}" /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    DeleteLegacyStartupTask();
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
    DataDir := ExpandConstant('{localappdata}\NewKartPanneauLed');
    if DirExists(DataDir) then
    begin
      if MsgBox('Supprimer aussi la configuration et les journaux enregistrés (' + DataDir + ') ?',
        mbConfirmation, MB_YESNO) = IDYES then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
