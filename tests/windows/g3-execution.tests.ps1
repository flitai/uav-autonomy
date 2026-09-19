#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PythonExecutable,
    [string]$Configuration,
    [string]$RunId,
    [string]$BaselineRunId
)
$ErrorActionPreference='Stop'
& (Join-Path $PSScriptRoot '../../scripts/windows/run-g3-execution.ps1') -PythonExecutable $PythonExecutable -Configuration $Configuration -RunId $RunId -BaselineRunId $BaselineRunId -Verify
if($LASTEXITCODE -ne 0) { throw 'G3 execution acceptance failed.' }
