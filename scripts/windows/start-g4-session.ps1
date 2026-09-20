#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PythonExecutable,
    [ValidateSet('Original','Mixed20')][string]$Scene='Mixed20',
    [ValidateSet('Headless','Gui')][string]$Mode='Gui',
    [switch]$ValidateEntry
)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$output=@(& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'check-g3-baseline.ps1') -PythonExecutable $PythonExecutable)
if($LASTEXITCODE -ne 0) { throw 'Current source qualification failed.' }
$ids=@($output | ForEach-Object { if($_ -match '^G3_T01_RUN_ID=(.+)$') { $Matches[1] } })
if($ids.Count -ne 1) { throw 'Unique baseline required.' }
$config=Get-Content -Raw -Encoding UTF8 (Join-Path $root 'config/windows-java-toolchain.json') | ConvertFrom-Json
$jdk=@($config.tools | Where-Object { $_.id -eq 'jdk' })
if($jdk.Count -ne 1) { throw 'Unique locked JDK required.' }
$javaHome=Join-Path (Join-Path $root '.tools') $jdk[0].installDirectory
$extra=@()
if($ValidateEntry) { $extra += '--validate-entry' }
& $PythonExecutable -I -B -X utf8 (Join-Path $root 'scripts/g4_session/runtime.py') --root $root --baseline-run-id $ids[0] --java-home $javaHome --scene $Scene --mode $Mode @extra
exit $LASTEXITCODE
