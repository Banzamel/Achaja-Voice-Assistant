# Instalator Achai (Windows). Uruchom: prawy przycisk -> "Uruchom w programie PowerShell"
# albo w terminalu:  powershell -ExecutionPolicy Bypass -File install.ps1
# Wszystko lokalnie w folderze projektu - nic nie jest instalowane w systemie.
[CmdletBinding()]
param(
    [ValidateSet("pl", "en")]
    [string]$Language = "pl",  # język słów sterujących i odpowiedzi / control-word and reply language
    [switch]$SkipModel,        # pomiń pobieranie modelu Vosk / skip the Vosk model download
    [switch]$Autostart         # skrót w autostarcie Windows / add a Windows startup shortcut
)

$settingsLanguage = @{ pl = "polish"; en = "english" }[$Language]
$rulesFile      = @{ pl = $null;   en = "docs\CLAUDE.en.md" }[$Language]

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

# 3. Konfiguracja (jeden plik dla wszystkich języków; blok "languages" wybiera słowa i model)
$config = Join-Path $root "config.json"
if (-not (Test-Path $config)) {
    Copy-Item (Join-Path $root "config.example.json") $config
    Write-Host "Utworzono config.json - dostosuj mikrofon, foldery projektów i głośnik." -ForegroundColor Yellow
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

# 5. Zasady asystentki w wybranym języku (polski jest wersją domyślną w repozytorium)
if ($rulesFile) {
    Copy-Item (Join-Path $root $rulesFile) (Join-Path $root ".claude\CLAUDE.md") -Force
    Write-Host "Ustawiono zasady asystentki w języku: $Language"
}

# 6. Ustawienia sesji Claude (hooki głosowe) z prawdziwą ścieżką projektu
$settings = Join-Path $root ".claude\settings.json"
if (-not (Test-Path $settings)) {
    $template = Get-Content (Join-Path $root "setup\settings.json") -Raw -Encoding UTF8
    $template = $template -replace '__PROJECT_DIR__', ($root -replace '\\', '/')
    $template = $template -replace '"language": "polish"', ("""language"": ""{0}""" -f $settingsLanguage)
    [IO.File]::WriteAllText($settings, $template, (New-Object Text.UTF8Encoding $false))
    Write-Host "Utworzono .claude\settings.json (hooki odpowiedzi głosowej)."
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
Write-Host "  Jezyk: install.ps1 -Language pl | -Language en"
Write-Host "  Mikrofony i wyjścia audio wypiszesz komendą:"
Write-Host "     .venv\Scripts\python.exe .claude\scripts\listener.py --devices"
