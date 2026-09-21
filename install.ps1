# Instalator Achai (Windows). Uruchom: prawy przycisk -> "Uruchom w programie PowerShell"
# albo w terminalu:  powershell -ExecutionPolicy Bypass -File install.ps1
# Wszystko lokalnie w folderze projektu - nic nie jest instalowane w systemie.
[CmdletBinding()]
param(
    [switch]$SkipModel,      # pomiń pobieranie modelu Vosk
    [switch]$WithAdb,        # pobierz narzędzia Android (sterowanie telewizorem)
    [switch]$Autostart       # dodaj skrót do autostartu Windows
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Write-Host "== Achaja - instalacja w $root ==" -ForegroundColor Cyan

# 1. Python
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { throw "Nie znaleziono Pythona. Zainstaluj Python 3.11+ (python.org) i uruchom ponownie." }
$version = & $python -c "import sys; print('%d.%d' % sys.version_info[:2])"
Write-Host "Python $version ($python)"

# 2. Środowisko wirtualne + biblioteki
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Tworzę środowisko .venv..."
    & $python -m venv (Join-Path $root ".venv")
}
Write-Host "Instaluję biblioteki (requirements.txt)..."
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -r (Join-Path $root "requirements.txt")

# 3. Model rozpoznawania słów kluczowych (Vosk, offline, ~50 MB)
$modelDir = Join-Path $root "models\vosk-model-small-pl-0.22"
if (-not $SkipModel -and -not (Test-Path $modelDir)) {
    Write-Host "Pobieram model mowy (Vosk PL, ~50 MB)..."
    New-Item -ItemType Directory -Force (Join-Path $root "models") | Out-Null
    $zip = Join-Path $root "models\model.zip"
    Invoke-WebRequest "https://alphacephei.com/vosk/models/vosk-model-small-pl-0.22.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive $zip -DestinationPath (Join-Path $root "models") -Force
    Remove-Item $zip
}

# 4. Konfiguracja
$config = Join-Path $root "config.json"
if (-not (Test-Path $config)) {
    Copy-Item (Join-Path $root "config.example.json") $config
    Write-Host "Utworzono config.json - dostosuj go (mikrofon, foldery projektów, głośnik)." -ForegroundColor Yellow
}

# 5. Ustawienia sesji Claude (hooki głosowe) z prawdziwą ścieżką projektu
$settings = Join-Path $root ".claude\settings.json"
if (-not (Test-Path $settings)) {
    $template = Get-Content (Join-Path $root "setup\settings.json") -Raw -Encoding UTF8
    $template = $template -replace '__PROJECT_DIR__', ($root -replace '\\', '/')
    [IO.File]::WriteAllText($settings, $template, (New-Object Text.UTF8Encoding $false))
    Write-Host "Utworzono .claude\settings.json (hooki odpowiedzi głosowej)."
}

# 6. Opcjonalnie: narzędzia Android (sterowanie telewizorem)
if ($WithAdb -and -not (Test-Path (Join-Path $root "tools\platform-tools\adb.exe"))) {
    Write-Host "Pobieram Android platform-tools..."
    New-Item -ItemType Directory -Force (Join-Path $root "tools") | Out-Null
    $zip = Join-Path $root "tools\platform-tools.zip"
    Invoke-WebRequest "https://dl.google.com/android/repository/platform-tools-latest-windows.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive $zip -DestinationPath (Join-Path $root "tools") -Force
    Remove-Item $zip
}

# 7. Opcjonalnie: autostart
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

Write-Host ""
Write-Host "Gotowe." -ForegroundColor Green
Write-Host "Następne kroki:"
Write-Host "  1. Sprawdź config.json (mikrofon, agents.project_roots, głośnik)."
Write-Host "  2. W Claude Code zaloguj się kontem claude.ai (dyktowanie wymaga konta, nie klucza API)."
Write-Host "  3. Uruchom start-achaja.cmd i powiedz slowo wybudzenia."
Write-Host "  Mikrofony i wyjścia audio wypiszesz komendą:"
Write-Host "     .venv\Scripts\python.exe .claude\scripts\listener.py --devices"
