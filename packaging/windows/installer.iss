#ifndef AppVersion
#define AppVersion "0.3.4"
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
UninstallDisplayIcon={app}\MTGA Constructed Testing.exe
SetupIconFile=..\icons\icon.ico
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=*.exe

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

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  { Restart Manager often misses a tray-only Qt process, then DeleteFile
    fails with ERROR_ACCESS_DENIED on the still-mapped exe. }
  Exec(ExpandConstant('{sys}\taskkill.exe'),
    '/IM "MTGA Constructed Testing.exe" /F',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;

