#ifndef Payload
  #error Payload directory is required
#endif
#ifndef InstallerPassword
  #error A private installer password is required
#endif
[Setup]
AppId=VastgamePersonalWindows
AppName=Vastgame
AppVersion=1.0.0
AppPublisher=Vastgame
DefaultDirName={localappdata}\Vastgame
DefaultGroupName=Vastgame
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.19041
OutputDir={#Output}
OutputBaseFilename=Vastgame-Setup-Personal
Compression=lzma2/fast
SolidCompression=yes
Encryption=yes
Password={#InstallerPassword}
EncryptionKeyDerivation=pbkdf2/600000
UninstallDisplayName=Vastgame (private WSL data retained)
DisableProgramGroupPage=yes
WizardStyle=modern
ChangesEnvironment=yes
[Files]
Source: "{#Payload}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
[Icons]
Name: "{group}\Vastgame"; Filename: "{app}\vastgame.cmd"; WorkingDir: "{app}"
Name: "{group}\Complete Vastgame Setup"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -NoExit -ExecutionPolicy Bypass -File ""{app}\Complete-Setup.ps1"""; WorkingDir: "{app}"
Name: "{group}\Moonlight"; Filename: "{app}\Moonlight\Moonlight.exe"; WorkingDir: "{app}\Moonlight"
Name: "{group}\Windows installation notes"; Filename: "{app}\WINDOWS-README.txt"
[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Check: NeedsPath; Flags: preservestringtype
[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -NoExit -ExecutionPolicy Bypass -File ""{app}\Complete-Setup.ps1"""; Description: "Finish WSL setup and account checks"; Flags: postinstall nowait skipifsilent
[Code]
function NeedsPath: Boolean;
var Existing: String;
begin
  RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Existing);
  Result := Pos(';' + Lowercase(ExpandConstant('{app}')) + ';', ';' + Lowercase(Existing) + ';') = 0;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var Existing, Remaining, Segment, AppPath: String;
    Separator: Integer;
begin
  if CurUninstallStep = usPostUninstall then begin
    if RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Existing) then begin
      AppPath := Lowercase(ExpandConstant('{app}'));
      Remaining := '';
      while Existing <> '' do begin
        Separator := Pos(';', Existing);
        if Separator = 0 then Separator := Length(Existing) + 1;
        Segment := Copy(Existing, 1, Separator - 1);
        Delete(Existing, 1, Separator);
        if Lowercase(Segment) <> AppPath then begin
          if Remaining <> '' then Remaining := Remaining + ';';
          Remaining := Remaining + Segment;
        end;
      end;
      RegWriteExpandStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Remaining);
    end;
  end;
end;
