; AeroLab Studio — Windows installer
;
; Build with Inno Setup 6 (https://jrsoftware.org/isinfo.php):
;     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\AeroLabStudio.iss
; or open this file in the Inno Setup Compiler and press F9.
;
; Expects PyInstaller to have produced dist\AeroLabStudio\ first:
;     pyinstaller AeroLabStudio.spec --noconfirm

#define AppName        "AeroLab Studio"
#define AppVersion     "1.0.0"
#define AppPublisher   "AeroLab Studio"
#define AppExe         "AeroLabStudio.exe"
#define SourceDir      "..\dist\AeroLabStudio"

[Setup]
AppId={{8E4C1F2A-6B3D-4A7E-9C51-2F8D7A0B4E13}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=
InfoBeforeFile=
OutputDir=..\dist
OutputBaseFilename=AeroLabStudio-Setup-{#AppVersion}
SetupIconFile=..\build_assets\aerolab.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; A per-user install needs no administrator rights; lowest+auto elevates only if the
; user picks a machine-wide location.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
AppComments=Equations, measurements and publication figures for aerogel-fibre research
AppReadmeFile={app}\README.md

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; \
    GroupDescription: "Additional shortcuts:"
Name: "associate"; Description: "Open &.aerolab session files with {#AppName}"; \
    GroupDescription: "File associations:"

[Files]
Source: "{#SourceDir}\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\*";         DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";               Filename: "{app}\{#AppExe}"
Name: "{group}\User guide";               Filename: "{app}\docs\USER_GUIDE.md"
Name: "{group}\Uninstall {#AppName}";     Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";         Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.aerolab"; ValueType: string; ValueName: ""; \
    ValueData: "AeroLabStudio.Session"; Flags: uninsdeletevalue; Tasks: associate
Root: HKA; Subkey: "Software\Classes\AeroLabStudio.Session"; ValueType: string; \
    ValueName: ""; ValueData: "AeroLab Studio session"; Flags: uninsdeletekey; Tasks: associate
Root: HKA; Subkey: "Software\Classes\AeroLabStudio.Session\DefaultIcon"; \
    ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"; Tasks: associate
Root: HKA; Subkey: "Software\Classes\AeroLabStudio.Session\shell\open\command"; \
    ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: associate

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Settings live in the user profile; leave them unless the user asks for a clean removal.
Type: filesandordirs; Name: "{app}\_internal\__pycache__"

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  SettingsDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    SettingsDir := ExpandConstant('{%USERPROFILE}\.aerolab_studio');
    if DirExists(SettingsDir) then
      if MsgBox('Remove your AeroLab Studio settings as well?' + #13#10 +
                'Saved sessions and exported files are never touched.',
                mbConfirmation, MB_YESNO) = IDYES then
        DelTree(SettingsDir, True, True, True);
  end;
end;
