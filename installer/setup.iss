; Elliott's Caspar Controller -- Inno Setup installer script
; Build: iscc /DMyAppVersion="2.0.2" setup.iss

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName      "Elliott's Caspar Controller"
#define MyAppSlug      "ElliottsCasparController"
#define MyAppPublisher "BlueElliott"
#define MyAppURL       "https://github.com/BlueElliott/Elliotts-Caspar-Controller"
#define MyAppExeName   "ElliottsCasparController.exe"
; Fixed GUID -- must never change between versions so in-place upgrades work correctly.
; No braces in the #define -- they are added at AppId using {{ escape syntax.
#define MyAppId "A3F7C2D1-8B4E-4F9A-B2C6-E1D8A3F7C2D1"

[Setup]
AppId={{{#MyAppId}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
; User-local Programs -- no admin rights needed.
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=Output
OutputBaseFilename={#MyAppSlug}Setup
SetupIconFile=..\static\esc_icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
; Close the running app silently during silent updates.
CloseApplications=yes
CloseApplicationsFilter={#MyAppExeName}
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Components]
Name: "main";   Description: "{#MyAppName}  (required)"; Types: full compact custom; Flags: fixed
Name: "caspar"; Description: "Lite Caspar Server -- CasparCG NDI engine (recommended, ~500 MB download)"; Types: full

[Files]
Source: "..\dist\{#MyAppSlug}\{#MyAppExeName}"; \
  DestDir: "{app}"; \
  Flags: ignoreversion; \
  Components: main

Source: "..\dist\{#MyAppSlug}\_internal\*"; \
  DestDir: "{app}\_internal"; \
  Flags: ignoreversion recursesubdirs createallsubdirs; \
  Components: main

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}";  Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; \
  Description: "Launch {#MyAppName} now"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\elliotts_caspar_config.json"
Type: files; Name: "{app}\*.config"
Type: files; Name: "{app}\*.old"

[Code]

var
  CasparDirPage: TInputDirWizardPage;
  FCasparInstallDir: String;

procedure InitializeWizard;
begin
  CasparDirPage := CreateInputDirPage(
    wpSelectComponents,
    'Lite Caspar Server Location',
    'Where should the Lite Caspar Server files be installed?',
    'CasparCG and its dependencies will be placed here (~500 MB). ' +
    'Point the controller at casparcg.exe inside this folder after launch.',
    False, ''
  );
  CasparDirPage.Add('');
  CasparDirPage.Values[0] := ExpandConstant('{sd}\CasparCG');
  FCasparInstallDir := ExpandConstant('{sd}\CasparCG');
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = CasparDirPage.ID then
    Result := not IsComponentSelected('caspar');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = CasparDirPage.ID then
  begin
    if Trim(CasparDirPage.Values[0]) = '' then
    begin
      MsgBox('Please select a folder for the Lite Caspar Server.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    FCasparInstallDir := CasparDirPage.Values[0];
  end;
end;

function GetCasparInstallDir(Param: String): String;
begin
  Result := FCasparInstallDir;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ZipUrl, ZipPath, ExtractDir, ScriptPath, PSContent, PSArgs: String;
  ResultCode: Integer;
begin
  if (CurStep = ssPostInstall) and IsComponentSelected('caspar') then
  begin
    ZipUrl     := 'https://github.com/BlueElliott/Elliotts-Caspar-Controller/releases/download/v{#MyAppVersion}/LiteCasparServer.zip';
    ZipPath    := ExpandConstant('{tmp}\LiteCasparServer.zip');
    ExtractDir := FCasparInstallDir;
    ScriptPath := ExpandConstant('{tmp}\DownloadCaspar.ps1');

    // Build and save a PS1 script to avoid inline quoting/escaping issues.
    PSContent :=
      '$url = ''' + ZipUrl + '''' + #13#10 +
      '$zip = ''' + ZipPath + '''' + #13#10 +
      '$out = ''' + ExtractDir + '''' + #13#10 +
      'try {' + #13#10 +
      '  Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing' + #13#10 +
      '  New-Item -ItemType Directory -Force -Path $out | Out-Null' + #13#10 +
      '  Expand-Archive -Path $zip -DestinationPath $out -Force' + #13#10 +
      '  Remove-Item -Path $zip -Force -ErrorAction SilentlyContinue' + #13#10 +
      '} catch { exit 1 }' + #13#10;
    SaveStringToFile(ScriptPath, PSContent, False);

    WizardForm.StatusLabel.Caption := 'Downloading Lite Caspar Server (~500 MB) -- please wait...';
    WizardForm.StatusLabel.Update;

    PSArgs := '-NonInteractive -ExecutionPolicy Bypass -File "' + ScriptPath + '"';

    if not Exec('powershell.exe', PSArgs, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or
       (ResultCode <> 0) then
    begin
      MsgBox(
        'Could not download or extract the Lite Caspar Server.' + #13#10 +
        'Check your internet connection and try downloading LiteCasparServer.zip' + #13#10 +
        'manually from the GitHub releases page:' + #13#10 +
        '{#MyAppURL}/releases',
        mbError, MB_OK
      );
    end;

    // Clean up temp files
    DeleteFile(ScriptPath);
    DeleteFile(ZipPath);
  end;
end;
