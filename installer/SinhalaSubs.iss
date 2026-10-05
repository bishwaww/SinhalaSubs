; Inno Setup script: makes SinhalaSubs-Setup-<version>.exe from dist\SinhalaSubs
; Build with build.bat (it passes the version), or:
;   ISCC.exe /DMyAppVersion=1.0.0 installer\SinhalaSubs.iss

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppName "SinhalaSubs"
#define MyAppExe "SinhalaSubs.exe"

[Setup]
; never change AppId: Windows uses it to know an update is the same app
AppId={{7C1E6A52-3B8E-4F0B-9D2A-51A6C0E4B9D1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=SinhalaSubs
VersionInfoVersion={#MyAppVersion}
; per-user install: no admin password needed, goes to %LOCALAPPDATA%\Programs\SinhalaSubs
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=SinhalaSubs-Setup-{#MyAppVersion}
SetupIconFile=..\sinhalasubs\data\icon.ico
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; close a running copy before updating it
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\SinhalaSubs\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Start {#MyAppName} now"; Flags: nowait postinstall skipifsilent

; Your settings, API key, backups and Whisper models live in %APPDATA%\SinhalaSubs.
; Uninstall leaves them there on purpose, so a reinstall keeps everything.
