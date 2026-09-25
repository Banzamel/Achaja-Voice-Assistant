; Instalator Achai (Inno Setup 6). Budowanie: setup\build-installer.ps1 (lokalnie albo w GitHub Actions).
; Pliki projektu i przenośny Python przygotowuje skrypt budujący w build\app i build\runtime.
; Po skopiowaniu plików instalator uruchamia install.ps1 (biblioteki, model mowy, hooki),
; a ten otwiera formularz konfiguracji w przeglądarce z modułami wybranymi w kreatorze.
; Instalacja bez okien: AchajaSetup.exe /SILENT /COMPONENTS="voice,mail" /noconfigure=1

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F0B7C2E-4B7A-4E0C-9C55-3A1C4E7D2B90}
AppName=Achaja
AppVersion={#AppVersion}
AppVerName=Achaja {#AppVersion}
AppPublisher=Banzamel
AppPublisherURL=https://github.com/Banzamel/Achaja-Voice-Assistant
AppSupportURL=https://github.com/Banzamel/Achaja-Voice-Assistant/issues
DefaultDirName={localappdata}\Programs\Achaja
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=AchajaSetup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=yes
UninstallDisplayName=Achaja
CloseApplications=no

[Languages]
Name: "pl"; MessagesFile: "compiler:Languages\Polish.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
pl.TypeFull=Wszystkie moduły
en.TypeFull=All modules
pl.TypeCompact=Tylko asystentka głosowa
en.TypeCompact=Voice assistant only
pl.TypeCustom=Wybór modułów
en.TypeCustom=Choose modules
pl.CompVoice=Asystentka głosowa: nasłuch, dyktowanie, odpowiedzi głosem (wymagane)
en.CompVoice=Voice assistant: wake word, dictation, spoken answers (required)
pl.CompAgents=Agenci projektów: zlecanie pracy w Twoich projektach
en.CompAgents=Project agents: hand work to your own projects
pl.CompMail=Poczta: sortowanie skrzynek, raporty głosem, odpowiedzi
en.CompMail=Mail: mailbox sorting, spoken reports, replies
pl.CompHA=Home Assistant: sterowanie domem
en.CompHA=Home Assistant: home control
pl.TaskAutostart=Uruchamiaj Achaję razem z Windows
en.TaskAutostart=Start Achaja with Windows
pl.TaskDesktop=Skrót na pulpicie
en.TaskDesktop=Desktop shortcut
pl.ConfigName=Achaja - ustawienia
en.ConfigName=Achaja - settings
pl.Installing=Instaluję biblioteki, model mowy i otwieram formularz ustawień...
en.Installing=Installing libraries and the speech model, then opening the settings form...
pl.SetupFailed=Instalacja składników nie powiodła się (kod %1). Sprawdź połączenie z internetem i uruchom instalator ponownie.
en.SetupFailed=Installing components failed (code %1). Check the internet connection and run the installer again.
pl.NoClaude=Nie znaleziono Claude Code (polecenie „claude”).%n%nAchaja działa w Claude Code: zainstaluj go ze strony claude.com/claude-code i zaloguj się kontem claude.ai (dyktowanie wymaga konta).%n%nMożesz kontynuować instalację i doinstalować Claude Code później.
en.NoClaude=Claude Code (the "claude" command) was not found.%n%nAchaja runs inside Claude Code: install it from claude.com/claude-code and sign in with a claude.ai account (dictation needs one).%n%nYou can continue and install Claude Code later.
pl.LaunchNow=Uruchom Achaję
en.LaunchNow=Start Achaja

[Types]
Name: "full"; Description: "{cm:TypeFull}"
Name: "compact"; Description: "{cm:TypeCompact}"
Name: "custom"; Description: "{cm:TypeCustom}"; Flags: iscustom

[Components]
Name: "voice"; Description: "{cm:CompVoice}"; Types: full compact custom; Flags: fixed
Name: "agents"; Description: "{cm:CompAgents}"; Types: full
Name: "mail"; Description: "{cm:CompMail}"; Types: full
Name: "ha"; Description: "{cm:CompHA}"; Types: full

[Tasks]
Name: "autostart"; Description: "{cm:TaskAutostart}"
Name: "desktopicon"; Description: "{cm:TaskDesktop}"; Flags: unchecked

[Files]
Source: "..\build\app\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\build\runtime\*"; DestDir: "{app}\runtime"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Achaja"; Filename: "{app}\start-achaja.cmd"; WorkingDir: "{app}"
Name: "{autoprograms}\{cm:ConfigName}"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\setup\configure.py"""; WorkingDir: "{app}"
Name: "{autodesktop}\Achaja"; Filename: "{app}\start-achaja.cmd"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\Achaja"; Filename: "{app}\start-achaja.cmd"; WorkingDir: "{app}"; Flags: runminimized; Tasks: autostart

[Run]
Filename: "{app}\start-achaja.cmd"; WorkingDir: "{app}"; Description: "{cm:LaunchNow}"; Flags: postinstall nowait skipifsilent shellexec

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""{code:StopCommand}"""; Flags: runhidden; RunOnceId: "StopAchaja"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\models"
Type: filesandordirs; Name: "{app}\state"
Type: filesandordirs; Name: "{app}\.claude"
Type: filesandordirs; Name: "{app}\setup\__pycache__"
Type: files; Name: "{app}\config.json"
Type: files; Name: "{app}\.mcp.json"

[Code]
function StopCommand(Param: String): String;
begin
  { zatrzymuje nasłuch i pocztę Achai z tego folderu (pliki są wtedy zablokowane) }
  Result := 'Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like ''' +
    ExpandConstant('{app}') + '\*'' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }';
end;

function InitializeSetup(): Boolean;
var
  Code: Integer;
begin
  Result := True;
  if not WizardSilent() then
    if not Exec(ExpandConstant('{cmd}'), '/c where claude', '', SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then
      MsgBox(CustomMessage('NoClaude'), mbInformation, MB_OK);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -Command "' + StopCommand('') + '"', '',
       SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;

function SelectedModules(): String;
begin
  Result := 'voice';
  if WizardIsComponentSelected('agents') then Result := Result + ',agents';
  if WizardIsComponentSelected('mail') then Result := Result + ',mail';
  if WizardIsComponentSelected('ha') then Result := Result + ',ha';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
  Params: String;
begin
  if CurStep <> ssPostInstall then Exit;
  WizardForm.StatusLabel.Caption := CustomMessage('Installing');
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\install.ps1') + '"' +
    ' -Language ' + ActiveLanguage() +
    ' -Python "' + ExpandConstant('{app}\runtime\python.exe') + '"' +
    ' -Modules ' + SelectedModules();
  if WizardSilent() or (ExpandConstant('{param:noconfigure|0}') = '1') then
    Params := Params + ' -NoConfigure';
  if not Exec('powershell.exe', Params, ExpandConstant('{app}'), SW_SHOW, ewWaitUntilTerminated, Code) or (Code <> 0) then
    MsgBox(FmtMessage(CustomMessage('SetupFailed'), [IntToStr(Code)]), mbError, MB_OK);
end;
