# Tytuł i opis wydania z .github/releases/<wersja>.md - jeden styl dla wszystkich wydań na GitHubie.
# Pierwsza linia pliku "# Achaja X.Y.Z — podtytuł" to tytuł wydania, reszta to opis.
#   setup\release-notes.ps1 -Version 0.5.0            tworzy / poprawia wydanie v0.5.0 (gh, GH_TOKEN)
#   setup\release-notes.ps1 -All                       poprawia wszystkie istniejące wydania, które mają plik z opisem
# Używa go GitHub Actions: installer.yml przy nowym tagu i release-notes.yml po zmianie plików z opisami.
[CmdletBinding()]
param(
    [string]$Version = "",
    [switch]$All
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$dir = Join-Path $root ".github\releases"

function Publish($version) {
    $file = Join-Path $dir "$version.md"
    $tag = "v$version"
    if (-not (Test-Path $file)) {
        Write-Host "Brak $file - zostawiam opis wygenerowany przez GitHuba."
        gh release view $tag 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { gh release create $tag --title "Achaja $version" --generate-notes }
        return
    }
    $lines = Get-Content $file -Encoding UTF8
    $title = ($lines[0] -replace '^#\s*', '').Trim()
    $notes = Join-Path ([IO.Path]::GetTempPath()) "achaja-notes-$version.md"
    [IO.File]::WriteAllText($notes, (($lines | Select-Object -Skip 1) -join "`n").Trim() + "`n", (New-Object Text.UTF8Encoding $false))
    gh release view $tag 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        gh release edit $tag --title $title --notes-file $notes
    } else {
        gh release create $tag --title $title --notes-file $notes
    }
    if ($LASTEXITCODE -ne 0) { throw "Nie udało się zapisać wydania $tag." }
    Write-Host "Wydanie ${tag}: $title"
}

if ($All) {
    foreach ($f in Get-ChildItem $dir -Filter "*.md") {
        gh release view "v$($f.BaseName)" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { Publish $f.BaseName }   # nie tworzy wydań dla tagów, których jeszcze nie ma
    }
    $global:LASTEXITCODE = 0
} elseif ($Version) {
    Publish $Version
} else {
    throw "Podaj -Version X.Y.Z albo -All."
}
