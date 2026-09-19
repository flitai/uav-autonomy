#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PythonExecutable,
    [Parameter(Mandatory=$true)][string]$CompletionRunId,
    [string]$Configuration,
    [string]$RunId,
    [string]$BaselineRunId
)
$ErrorActionPreference='Stop'
& (Join-Path $PSScriptRoot '../../scripts/windows/run-g3-stability.ps1') -PythonExecutable $PythonExecutable -CompletionRunId $CompletionRunId -Configuration $Configuration -RunId $RunId -BaselineRunId $BaselineRunId -Verify
if($LASTEXITCODE -ne 0) { throw 'G3 stability acceptance failed.' }
