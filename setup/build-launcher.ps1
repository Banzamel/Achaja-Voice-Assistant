# Kompiluje Achaja.exe (setup\launcher\Achaja.cs) kompilatorem C# z .NET Framework 4 - jest w każdym Windows 10/11.
#   powershell -ExecutionPolicy Bypass -File setup\build-launcher.ps1 [-Out <plik.exe>] [-Version 0.5.0]
[CmdletBinding()]
param(
    [string]$Out = "",
    [string]$Version = ""
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
if (-not $Out) { $Out = Join-Path $root "Achaja.exe" }
if (-not $Version) {
    $Version = [regex]::Match((Get-Content (Join-Path $root ".claude\scripts\common.py") -Raw), '__version__ = "([^"]+)"').Groups[1].Value
}
$numeric = [regex]::Match($Version, '^\d+(\.\d+){0,3}').Value   # "0.5.0-dev" -> "0.5.0"
if (-not $numeric) { $numeric = "0.0.0" }

$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) { $csc = Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe" }
if (-not (Test-Path $csc)) { throw "Nie znaleziono kompilatora C# (.NET Framework 4)." }

$src = Join-Path ([IO.Path]::GetTempPath()) "Achaja-launcher.cs"
(Get-Content (Join-Path $PSScriptRoot "launcher\Achaja.cs") -Raw -Encoding UTF8) -replace '__VERSION__', $numeric |
    Set-Content $src -Encoding UTF8
& $csc /nologo /target:winexe /optimize+ /codepage:65001 "/win32icon:$(Join-Path $PSScriptRoot 'assets\achaja.ico')" `
    "/out:$Out" /r:System.Windows.Forms.dll /r:System.Core.dll $src
$code = $LASTEXITCODE
Remove-Item $src -ErrorAction SilentlyContinue
if ($code -ne 0) { throw "Kompilacja Achaja.exe nie powiodła się." }
Write-Host "Achaja.exe: $Out ($numeric)"
