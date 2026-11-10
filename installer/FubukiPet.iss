; Review candidate. No publishing happens from this script.
#ifndef BundleDir
  #error Define BundleDir as the absolute path to the reviewed FubukiPet folder.
#endif
#ifndef OutputDir
  #define OutputDir "..\..\deliverables"
#endif

[Setup]
AppId={{8A5CF21F-28C9-4518-9B29-EEEB1C766936}
AppName=Fubuki Pet Review
AppVersion=1.0.0.1
AppPublisher=Fubuki Pet contributors
DefaultDirName={localappdata}\Programs\FubukiPet-Review
DefaultGroupName=Fubuki Pet Review
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=FubukiPet-Windows-x64-Setup-REVIEW
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=yes
DisableProgramGroupPage=yes
DisableDirPage=yes
UninstallDisplayIcon={app}\FubukiPet.exe
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
Uninstallable=yes
#ifdef TestMode
CreateUninstallRegKey=no
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

#ifndef TestMode
[Icons]
Name: "{userprograms}\Fubuki Pet Review"; Filename: "{app}\FubukiPet.exe"; WorkingDir: "{app}"
#endif

; Startup, hooks and post-install execution are deliberately user actions.
; Personal settings in %LOCALAPPDATA%\FubukiPet are never deleted.
