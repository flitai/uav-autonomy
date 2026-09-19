#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PythonExecutable,
    [Parameter(Mandatory=$true)][string]$StabilityRunId,
    [string]$Configuration,
    [string]$RunId,
    [string]$BaselineRunId
)
$ErrorActionPreference='Stop'
& (Join-Path $PSScriptRoot '../../scripts/windows/run-g3-acceptance.ps1') -PythonExecutable $PythonExecutable -StabilityRunId $StabilityRunId -Configuration $Configuration -RunId $RunId -BaselineRunId $BaselineRunId
if($LASTEXITCODE -ne 0) { throw 'G3 stage acceptance failed.' }
