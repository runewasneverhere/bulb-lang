#define AppName "Bulb"
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{BC9A70A4-0E0D-41D8-9CC3-C20CF8FD91E3}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=runewasneverhere
DefaultDirName={localappdata}\Programs\Bulb
DefaultGroupName=Bulb
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
LicenseFile=..\..\LICENSE
SetupIconFile=..\..\bulbicon.ico
WizardSmallImageFile=..\..\bulbicon.png
OutputDir=..\..\dist\installer
OutputBaseFilename=bulb-setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\bulb.exe

[Tasks]
Name: "addtopath"; Description: "Add Bulb to your user PATH"; GroupDescription: "Additional options:"; Flags: checkedonce

[Files]
Source: "..\..\dist\bulb.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\COPYRIGHT"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\examples\*.bulb"; DestDir: "{app}\examples"; Flags: ignoreversion

[Icons]
Name: "{group}\Bulb README"; Filename: "{app}\README.md"; IconFilename: "{app}\bulb.exe"
Name: "{group}\Bulb examples"; Filename: "{app}\examples"; IconFilename: "{app}\bulb.exe"

[Code]
function HasPathEntry(PathValue, Directory: string): Boolean;
var
  Remaining, Entry: string;
  Separator: Integer;
begin
  Result := False;
  Remaining := PathValue;
  while Remaining <> '' do begin
    Separator := Pos(';', Remaining);
    if Separator = 0 then begin
      Entry := Remaining;
      Remaining := '';
    end else begin
      Entry := Copy(Remaining, 1, Separator - 1);
      Delete(Remaining, 1, Separator);
    end;
    if CompareText(Trim(Entry), Directory) = 0 then begin
      Result := True;
      Exit;
    end;
  end;
end;

function RemovePathEntry(PathValue, Directory: string): string;
var
  Remaining, Entry: string;
  Separator: Integer;
begin
  Result := '';
  Remaining := PathValue;
  while Remaining <> '' do begin
    Separator := Pos(';', Remaining);
    if Separator = 0 then begin
      Entry := Remaining;
      Remaining := '';
    end else begin
      Entry := Copy(Remaining, 1, Separator - 1);
      Delete(Remaining, 1, Separator);
    end;
    if CompareText(Trim(Entry), Directory) <> 0 then begin
      if Result <> '' then Result := Result + ';';
      Result := Result + Entry;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ExistingPath, NewPath, AppPath: string;
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('addtopath') then begin
    AppPath := ExpandConstant('{app}');
    if not RegQueryStringValue(HKCU, 'Environment', 'Path', ExistingPath) then
      ExistingPath := '';
    if not HasPathEntry(ExistingPath, AppPath) then begin
      if ExistingPath = '' then
        NewPath := AppPath
      else
        NewPath := ExistingPath + ';' + AppPath;
      if RegWriteExpandStringValue(HKCU, 'Environment', 'Path', NewPath) then
        RegWriteDWordValue(HKCU, 'Software\Bulb', 'AddedToPath', 1);
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ExistingPath, NewPath: string;
  AddedToPath: Cardinal;
begin
  if CurUninstallStep = usUninstall then begin
    if RegQueryDWordValue(HKCU, 'Software\Bulb', 'AddedToPath', AddedToPath) and (AddedToPath = 1) then begin
      if RegQueryStringValue(HKCU, 'Environment', 'Path', ExistingPath) then begin
        NewPath := RemovePathEntry(ExistingPath, ExpandConstant('{app}'));
        RegWriteExpandStringValue(HKCU, 'Environment', 'Path', NewPath);
      end;
      RegDeleteValue(HKCU, 'Software\Bulb', 'AddedToPath');
    end;
  end;
end;