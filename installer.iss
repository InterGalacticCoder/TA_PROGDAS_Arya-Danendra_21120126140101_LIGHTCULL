[Setup]
AppName=LightCull
AppVersion=1.0
DefaultDirName={autopf}\LightCull
DefaultGroupName=LightCull
OutputDir=dist_installer
OutputBaseFilename=LightCull-Windows-Setup
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest

[Tasks]
Name: "desktopicon"; Description: "Buat shortcut di Desktop"; GroupDescription: "Ikon Tambahan:"

[Files]
Source: "dist\LightCull\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\LightCull"; Filename: "{app}\LightCull.exe"
Name: "{autodesktop}\LightCull"; Filename: "{app}\LightCull.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LightCull.exe"; Description: "Jalankan LightCull"; Flags: nowait postinstall skipifsilent
