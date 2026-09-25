# Instalator Achai (Windows). Uruchom: prawy przycisk -> "Uruchom w programie PowerShell"
# albo w terminalu:  powershell -ExecutionPolicy Bypass -File install.ps1
# Wszystko lokalnie w folderze projektu - nic nie jest instalowane w systemie.
# Instalator .exe (setup\installer.iss) wywołuje ten sam skrypt z własnym Pythonem (-Python).
[CmdletBinding()]
param(
    [ValidateSet("pl", "en")]
    [string]$Language = "pl",  # język słów sterujących i odpowiedzi / control-word and reply language
    [string]$Python = "",      # interpreter do utworzenia .venv (domyślnie python z PATH) / interpreter for .venv
    [string]$Modules = "voice,agents,mail,ha",  # moduły w formularzu konfiguracji / modules shown in the setup form
    [switch]$SkipModel,        # pomiń pobieranie modelu Vosk / skip the Vosk model download
    [switch]$Autostart,        # skrót w autostarcie Windows / add a Windows startup shortcut
    [switch]$NoConfigure       # nie otwieraj formularza konfiguracji / don't open the setup form
)

$settingsLanguage = @{ pl = "polish"; en = "english" }[$Language]

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest z paskiem postępu jest wielokrotnie wolniejszy
$root = $PSScriptRoot
Write-Host "== Achaja - instalacja w $root ==" -ForegroundColor Cyan

# 1. Python
if (-not $Python) { $Python = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $Python -or -not (Test-Path $Python)) {
    throw "Nie znaleziono Pythona. Zainstaluj Python 3.11+ (python.org) albo użyj instalatora AchajaSetup.exe."
}
$version = & $Python -c "import sys; print('%d.%d' % sys.version_info[:2])"
Write-Host "Python $version ($Python)"

# 2. Środowisko wirtualne + biblioteki
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Tworzę środowisko .venv..."
    & $Python -m venv (Join-Path $root ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Nie udało się utworzyć .venv." }
}
Write-Host "Instaluję biblioteki (requirements.txt)..."
& $venvPython -m pip install --quiet --disable-pip-version-check --upgrade pip
& $venvPython -m pip install --quiet --disable-pip-version-check -r (Join-Path $root "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Instalacja bibliotek nie powiodła się (sprawdź połączenie z internetem)." }

# 3. Konfiguracja (jeden plik dla wszystkich języków; blok "languages" wybiera słowa i model)
$config = Join-Path $root "config.json"
if (-not (Test-Path $config)) {
    Copy-Item (Join-Path $root "config.example.json") $config
    Write-Host "Utworzono config.json."
}
$configData = Get-Content $config -Raw -Encoding UTF8 | ConvertFrom-Json
if ($configData.language -ne $Language) {
    $patched = (Get-Content $config -Raw -Encoding UTF8) -replace '"language": "\w+"', ("""language"": ""{0}""" -f $Language)
    [IO.File]::WriteAllText($config, $patched, (New-Object Text.UTF8Encoding $false))   # bez BOM - czyta to Python
    $configData = Get-Content $config -Raw -Encoding UTF8 | ConvertFrom-Json
}
$modelName = $configData.languages.$Language.model

# 4. Model rozpoznawania słów kluczowych (Vosk, offline, ~50 MB)
$modelDir = Join-Path $root "models\$modelName"
if (-not $SkipModel -and -not (Test-Path $modelDir)) {
    Write-Host "Pobieram model mowy / downloading speech model ($modelName, ~50 MB)..."
    New-Item -ItemType Directory -Force (Join-Path $root "models") | Out-Null
    $zip = Join-Path $root "models\model.zip"
    Invoke-WebRequest "https://alphacephei.com/vosk/models/$modelName.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive $zip -DestinationPath (Join-Path $root "models") -Force
    Remove-Item $zip
}

# 5. Ustawienia sesji Claude (hooki głosowe) z prawdziwą ścieżką projektu
$settings = Join-Path $root ".claude\settings.json"
$template = Get-Content (Join-Path $root "setup\settings.json") -Raw -Encoding UTF8
$template = $template -replace '__PROJECT_DIR__', ($root -replace '\\', '/')
$template = $template -replace '"language": "polish"', ("""language"": ""{0}""" -f $settingsLanguage)
if (-not (Test-Path $settings) -or (Get-Content $settings -Raw -Encoding UTF8) -notmatch [regex]::Escape(($root -replace '\\', '/'))) {
    [IO.File]::WriteAllText($settings, $template, (New-Object Text.UTF8Encoding $false))   # także po przeniesieniu folderu
    Write-Host "Utworzono .claude\settings.json (hooki odpowiedzi głosowej)."
}

# 6. Opcjonalnie: autostart
if ($Autostart) {
    $lnk = Join-Path ([Environment]::GetFolderPath('Startup')) "Achaja.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $s = $shell.CreateShortcut($lnk)
    $s.TargetPath = Join-Path $root "start-achaja.cmd"
    $s.WorkingDirectory = $root
    $s.WindowStyle = 7
    $s.Description = "Achaja - nasłuch głosowy"
    $s.Save()
    Write-Host "Dodano do autostartu: $lnk"
}

# 7. Claude Code - wymagany do działania (dyktowanie + sesja Achai)
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "UWAGA: nie znaleziono Claude Code (polecenie 'claude')." -ForegroundColor Yellow
    Write-Host "  Zainstaluj go: https://claude.com/claude-code  i zaloguj się kontem claude.ai." -ForegroundColor Yellow
}

# 8. Formularz konfiguracji w przeglądarce (mikrofon, głośnik, projekty, poczta, Home Assistant)
if (-not $NoConfigure) {
    Write-Host ""
    Write-Host "Otwieram formularz konfiguracji w przeglądarce - zapisz go, aby zakończyć."
    & $venvPython (Join-Path $root "setup\configure.py") --modules $Modules
}

Write-Host ""
Write-Host "Gotowe." -ForegroundColor Green
Write-Host "  Start: start-achaja.cmd, potem powiedz słowo wybudzenia."
Write-Host "  Zmiana ustawień później: .venv\Scripts\python.exe setup\configure.py"
