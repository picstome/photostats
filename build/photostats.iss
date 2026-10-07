; Inno Setup script for the Windows installer.
; Build with:  iscc /DMyAppVersion=1.0.0 build\photostats.iss
; Produces dist\PhotoStats-Setup.exe

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define AppName "Photo Stats"
#define AppPublisher "Picstome.com"
#define AppURL "https://picstome.com"
#define AppExeName "Photo Stats.exe"
#define AppIcon "..\\build\\assets\\icon.ico"

[Setup]
AppId={{7C4B1B4E-9E6A-4B1F-9E31-2C5A7E8D4A10}
AppName={#AppName}
AppVersion={#MyAppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
SetupIconFile={#AppIcon}
UninstallDisplayIcon={app}\{#AppExeName}
DefaultDirName={autopf}\Photo Stats
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=PhotoStats-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Per-user install by default: avoids needing admin rights.
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Photo Stats\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;