# Publikuje nowe wydanie Achai: podnosi wersję, robi commit i tag v<wersja> i wypycha je na GitHuba.
# Najpierw napisz opis wydania w .github\releases\<wersja>.md (tytuł w pierwszej linii, jak w poprzednich).
# GitHub Actions (.github/workflows/installer.yml) buduje wtedy AchajaSetup-<wersja>.exe z Achaja.exe
# i dołącza go do wydania - zainstalowane Achaje same go znajdą, pobiorą i zainstalują.
#   powershell -ExecutionPolicy Bypass -File setup\release.ps1 -Version 0.5.0
#   ... -DryRun    tylko pokazuje, co zrobi
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version,
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

function Run($cmd) {
    Write-Host "> $cmd" -ForegroundColor Cyan
    if (-not $DryRun) {
        Invoke-Expression $cmd
        if ($LASTEXITCODE -ne 0) { throw "Polecenie nie powiodło się: $cmd" }
    }
}

$branch = git rev-parse --abbrev-ref HEAD
if ($branch -ne "main") { throw "Wydania robimy z gałęzi main (teraz: $branch)." }
if (git status --porcelain -- . ":!.github/releases") { throw "Masz niezapisane zmiany - zrób commit albo je odłóż." }
Run "git pull --ff-only origin main"
if (git tag --list "v$Version") { throw "Tag v$Version już istnieje." }
$notes = Join-Path $root ".github\releases\$Version.md"
if (-not (Test-Path $notes)) {
    throw "Brak opisu wydania .github\releases\$Version.md - pierwsza linia '# Achaja $Version — podtytuł', dalej lista zmian (wzór: poprzednie pliki w tym folderze)."
}

$common = Join-Path $root ".claude\scripts\common.py"
$text = Get-Content $common -Raw -Encoding UTF8
$old = [regex]::Match($text, '__version__ = "([^"]+)"').Groups[1].Value
if ([version]$Version -le [version]$old) { throw "Nowa wersja $Version musi być wyższa niż $old." }
Write-Host "Wersja: $old -> $Version"
if (-not $DryRun) {
    [IO.File]::WriteAllText($common, ($text -replace '__version__ = "[^"]+"', "__version__ = ""$Version"""),
                            (New-Object Text.UTF8Encoding $false))
}
Run "git add -- '$notes'"
Run "git commit -am 'Wersja $Version'"
Run "git tag -a v$Version -m 'Achaja $Version'"
Run "git push origin main"
Run "git push origin v$Version"
Write-Host ""
Write-Host "Gotowe. Instalator buduje się w GitHub Actions (zakładka Actions -> Installer)," -ForegroundColor Green
Write-Host "a po kilku minutach pojawi się w https://github.com/Banzamel/Achaja-Voice-Assistant/releases" -ForegroundColor Green
