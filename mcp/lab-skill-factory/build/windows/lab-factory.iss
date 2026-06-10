#define AppDisplayName "Lab Factory"
#ifndef AppVersion
#define AppVersion "0.1.0-beta"
#endif
#ifndef AppPublisher
#define AppPublisher "Lab Factory"
#endif
#ifndef SourceDir
#define SourceDir "..\..\dist\windows"
#endif
#ifndef McpDir
#define McpDir "..\.."
#endif
#ifndef OutputDir
#define OutputDir "..\..\dist\windows\installer"
#endif
#ifndef AppExeName
#define AppExeName "lab-factory.exe"
#endif

[Setup]
AppId={{7C2AC7C7-4B82-4EF3-930B-7E9D00BDF6B3}
AppName={#AppDisplayName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={userpf}\Lab Factory
DefaultGroupName=Lab Factory
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=LabFactory-{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
UninstallDisplayIcon={app}\lab-factory.exe
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#SourceDir}\{#AppExeName}"; DestDir: "{app}"; DestName: "lab-factory.exe"; Flags: ignoreversion
Source: "{#McpDir}\README.md"; DestDir: "{app}"; DestName: "README.md"; Flags: ignoreversion
Source: "{#McpDir}\build\windows\README-WINDOWS.md"; DestDir: "{app}"; DestName: "README-WINDOWS.md"; Flags: ignoreversion
Source: "{#McpDir}\client-configs\*"; DestDir: "{app}\client-configs"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#McpDir}\docs\*"; DestDir: "{app}\docs"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Lab Factory CLI"; Filename: "{cmd}"; Parameters: "/K ""{app}\lab-factory.exe"" status"; WorkingDir: "{app}"
Name: "{group}\Install Codex MCP Config"; Filename: "{cmd}"; Parameters: "/K ""{app}\lab-factory.exe"" install --target codex"; WorkingDir: "{app}"
Name: "{group}\Install Claude Code MCP Config"; Filename: "{cmd}"; Parameters: "/K ""{app}\lab-factory.exe"" install --target claude"; WorkingDir: "{app}"
Name: "{group}\Lab Factory Windows README"; Filename: "{app}\README-WINDOWS.md"
Name: "{group}\Lab Factory README"; Filename: "{app}\README.md"
Name: "{group}\Lab Factory Agent Deployment Guide"; Filename: "{app}\docs\AGENT_MCP_DEPLOYMENT.md"
Name: "{group}\Lab Factory Windows/macOS Usage Guide"; Filename: "{app}\docs\WINDOWS_MAC_USAGE.md"

[Run]
Filename: "{app}\README-WINDOWS.md"; Description: "Open Windows README"; Flags: postinstall shellexec skipifsilent unchecked
