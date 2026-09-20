#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PythonExecutable,
    [string]$BaselineRunId,
    [ValidateSet('Headless','Gui','Both')][string]$Mode='Both',
    [switch]$Diagnostic
)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
if(-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) { throw 'Explicit Python interpreter required.' }
$PythonExecutable=(Resolve-Path -LiteralPath $PythonExecutable).Path
if(-not $BaselineRunId) {
    $output=@(& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'check-g3-baseline.ps1') -PythonExecutable $PythonExecutable)
    if($LASTEXITCODE -ne 0) { throw 'Current formal source qualification failed.' }
    $ids=@($output | ForEach-Object { if($_ -match '^G3_T01_RUN_ID=(.+)$') { $Matches[1] } })
    if($ids.Count -ne 1) { throw 'Unique baseline identity required.' }
    $BaselineRunId=$ids[0]
}
$javaConfig=Get-Content -Raw -Encoding UTF8 (Join-Path $root 'config/windows-java-toolchain.json') | ConvertFrom-Json
# Resolve the project-locked JDK layout; the runtime rechecks qualified source.
$jdk=@($javaConfig.tools | Where-Object { $_.id -eq 'jdk' })
if($jdk.Count -ne 1) { throw 'Unique locked JDK required.' }
$javaHome=Join-Path (Join-Path $root '.tools') $jdk[0].installDirectory
if(-not (Test-Path -LiteralPath (Join-Path $javaHome 'bin/java.exe') -PathType Leaf)) { throw 'Qualified JDK missing.' }
[string[]]$modes=if($Mode -eq 'Both') { @('Headless','Gui') } else { @($Mode) }
$seconds=if($Diagnostic) { '60' } else { '1800' }
& $PythonExecutable -I -B -X utf8 (Join-Path $root 'scripts/g4_scale/runtime.py') --root $root --java-home $javaHome --baseline-run-id $BaselineRunId --seconds $seconds --modes @modes
exit $LASTEXITCODE
