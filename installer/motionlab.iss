; MotionLab installer (Inno Setup 6).
; Small bootstrapper: ships the app layer only; the first launch downloads
; the engine, the Python environment and the models from their original
; sources (see installer\bootstrap.ps1).

#define AppName "MotionLab"
#define AppVersion Trim(FileRead(FileOpen("..\VERSION")))
#define AppPublisher "NR Media"

[Setup]
AppId={{7E4A26D1-9C4B-4E2A-B7F0-3B1A2C9D5E71}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\MotionLab
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=MotionLab-Setup-{#AppVersion}
SetupIconFile=assets\motionlab.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\app\assets\motionlab.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "hungarian"; MessagesFile: "compiler:Languages\Hungarian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs ignoreversion; Excludes: "__pycache__\*,test_*.py,debug_*.py"
Source: "..\installer\bootstrap.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "..\installer\assets\*"; DestDir: "{app}\installer\assets"; Flags: ignoreversion
Source: "..\MotionLab.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\VERSION"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\MotionLab"; Filename: "{app}\MotionLab.bat"; IconFilename: "{app}\app\assets\motionlab.ico"; WorkingDir: "{app}"
Name: "{autodesktop}\MotionLab"; Filename: "{app}\MotionLab.bat"; IconFilename: "{app}\app\assets\motionlab.ico"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\MotionLab.bat"; Description: "{cm:LaunchProgram,MotionLab}"; Flags: postinstall skipifsilent shellexec

[UninstallDelete]
Type: filesandordirs; Name: "{app}\update_staging"
Type: filesandordirs; Name: "{app}\logs"
