# Buduje instalator AchajaSetup-<wersja>.exe w folderze dist\.
#   powershell -ExecutionPolicy Bypass -File setup\build-installer.ps1 -Version 0.3.0
# Kompilator Inno Setup: -Iscc <ścieżka do ISCC.exe>, ISCC z PATH albo (bez instalacji) obraz Dockera amake/innosetup.
# Do instalatora trafiają pliki śledzone przez git (bez config.json, state/, .venv/ itd.) i przenośny Python.
[CmdletBinding()]
param(
    [string]$Version = "0.0.0",
    [string]$Iscc = "",
    [string]$PythonRelease = "20260924",
    [string]$PythonVersion = "3.12.14"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = Split-Path $PSScriptRoot -Parent
$build = Join-Path $root "build"
$app = Join-Path $build "app"
$runtime = Join-Path $build "runtime"

# 1. Pliki projektu: śledzone + nowe nieignorowane (bez usuniętych)
if (Test-Path $app) { Remove-Item $app -Recurse -Force }
New-Item -ItemType Directory -Force $app | Out-Null
$files = git -C $root ls-files --cached --others --exclude-standard
foreach ($f in $files) {
    $src = Join-Path $root $f
    if (-not (Test-Path $src -PathType Leaf) -or $f -like ".github/*" -or $f -like "setup/installer.iss" -or $f -like "setup/build-installer.ps1") { continue }
    $dst = Join-Path $app $f
    New-Item -ItemType Directory -Force (Split-Path $dst -Parent) | Out-Null
    Copy-Item $src $dst
}
Write-Host "Pliki projektu: $((Get-ChildItem $app -Recurse -File).Count)"

# 2. Przenośny Python (python-build-standalone) - bez instalacji w systemie użytkownika
if (-not (Test-Path (Join-Path $runtime "python.exe"))) {
    $cache = Join-Path $build "cache"
    New-Item -ItemType Directory -Force $cache | Out-Null
    $name = "cpython-$PythonVersion+$PythonRelease-x86_64-pc-windows-msvc-install_only.tar.gz"
    $archive = Join-Path $cache $name
    if (-not (Test-Path $archive)) {
        $url = "https://github.com/astral-sh/python-build-standalone/releases/download/$PythonRelease/" + $name.Replace("+", "%2B")
        Write-Host "Pobieram Pythona $PythonVersion..."
        Invoke-WebRequest $url -OutFile $archive -UseBasicParsing
    }
    $extract = Join-Path $build "python-extract"
    if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
    New-Item -ItemType Directory -Force $extract | Out-Null
    & (Join-Path $env:SystemRoot "System32\tar.exe") -xzf $archive -C $extract   # systemowy tar (tar z Gita nie rozumie C:)
    if ($LASTEXITCODE -ne 0) { throw "Nie udało się rozpakować Pythona." }
    if (Test-Path $runtime) { Remove-Item $runtime -Recurse -Force }
    Move-Item (Join-Path $extract "python") $runtime
    Remove-Item $extract -Recurse -Force
}
Write-Host "Python: $(& (Join-Path $runtime 'python.exe') --version)"

# 3. Kompilacja
New-Item -ItemType Directory -Force (Join-Path $root "dist") | Out-Null
if (-not $Iscc) {
    $found = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($found) { $Iscc = $found.Source }
    elseif (Test-Path "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") { $Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
}
if ($Iscc) {
    & $Iscc "/DAppVersion=$Version" (Join-Path $root "setup\installer.iss")
} else {
    Write-Host "Brak ISCC - kompiluję w Dockerze (amake/innosetup)..."
    $ErrorActionPreference = "Continue"   # docker pisze postęp na stderr
    docker run --rm -v "${root}:/work" amake/innosetup "/DAppVersion=$Version" setup/installer.iss
}
if ($LASTEXITCODE -ne 0) { throw "Kompilacja instalatora nie powiodła się." }
Get-ChildItem (Join-Path $root "dist") -Filter "AchajaSetup-$Version.exe" | ForEach-Object {
    Write-Host ("Gotowe: {0} ({1:N0} MB)" -f $_.FullName, ($_.Length / 1MB)) -ForegroundColor Green
}
