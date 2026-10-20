; Installer HORECA SnackYou — agent casă de marcat.
; Instalare fără drepturi de admin (în %LOCALAPPDATA%), configurare ghidată la
; final, pornire automată la boot (agentul își pune singur task-ul schtasks).

#define AppName "HORECA SnackYou"
#define AppVer "1.0.11"
#define ExeName "horeca-snackyou.exe"

[Setup]
AppId={{8F3C2A10-7B4D-4E9A-9C21-1A2B3C4D5E6F}}
AppName={#AppName}
AppVersion={#AppVer}
AppPublisher=SnackYou
DefaultDirName={localappdata}\HorecaSnackYou
DisableDirPage=yes
UsePreviousAppDir=yes
CloseApplications=yes
CloseApplicationsFilter=horeca-snackyou.exe,snackyou-diagnostic.exe
RestartApplications=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installer_out
OutputBaseFilename=horeca-snackyou-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#AppName}

[Files]
Source: "dist\{#ExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\snackyou-diagnostic.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Diagnostic Z SnackYou"; Filename: "{app}\snackyou-diagnostic.exe"
Name: "{autoprograms}\HORECA SnackYou"; Filename: "{app}\{#ExeName}"; Parameters: "run"
Name: "{autoprograms}\Configurează HORECA SnackYou"; Filename: "{app}\{#ExeName}"; Parameters: "setup"
Name: "{autodesktop}\HORECA SnackYou"; Filename: "{app}\{#ExeName}"; Parameters: "run"; Tasks: desktopicon
; Pornire automată la fiecare login — folder Startup (fără admin, fără schtasks).
Name: "{userstartup}\HorecaSnackYou"; Filename: "{app}\{#ExeName}"; Parameters: "run"

[Tasks]
Name: "desktopicon"; Description: "Creează scurtătură pe Desktop"; Flags: unchecked

[Run]
Filename: "{app}\snackyou-diagnostic.exe"; Description: "Diagnostic Z automat (fara oprirea agentului)"; Flags: postinstall nowait skipifsilent unchecked
; La final: configurarea ghidată (conectare UnityPOS + cod din aplicație) →
; agentul își activează singur pornirea automată și începe sincronizarea.
Filename: "{app}\{#ExeName}"; Parameters: "setup"; Description: "Configurează acum (prima instalare)"; Flags: postinstall nowait skipifsilent; Check: not HasExistingConfig
Filename: "{app}\{#ExeName}"; Parameters: "run"; Description: "Porneste agentul cu configuratia existenta"; Flags: postinstall nowait skipifsilent; Check: HasExistingConfig

[UninstallRun]
; La dezinstalare: scoate task-ul de pornire automată.
Filename: "{app}\{#ExeName}"; Parameters: "uninstall"; Flags: runhidden; RunOnceId: "RemoveAutostart"

[Code]
function HasExistingConfig: Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\horeca-snackyou.config.json'));
end;
