#ifndef AppVersion
#define AppVersion "0.2.0"
#endif

[Setup]
AppId={{A7AF7A18-6745-4CD7-873C-D9F4569FB513}
AppName=MTGA Constructed Testing
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\MTGA Constructed Testing
DefaultGroupName=MTGA Constructed Testing
OutputDir=..\..\artifacts
OutputBaseFilename=MTGA-Constructed-Testing-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=MTGA Constructed Testing
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "autostart"; Description: "Start automatically when I sign in"; GroupDescription: "Startup:"; Flags: checkedonce

[Files]
Source: "..\..\dist\MTGA Constructed Testing\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\MTGA Constructed Testing"; Filename: "{app}\MTGA Constructed Testing.exe"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "MTGA Constructed Testing"; ValueData: """{app}\MTGA Constructed Testing.exe"" --background"; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\MTGA Constructed Testing.exe"; Description: "Open MTGA Constructed Testing"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/IM ""MTGA Constructed Testing.exe"" /F"; Flags: runhidden; RunOnceId: "StopClient"
