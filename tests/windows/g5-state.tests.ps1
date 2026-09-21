#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,[Parameter(Mandatory=$true)][string]$BuildRunId,[string]$BaselineRunId)
. (Join-Path $PSScriptRoot '../../scripts/windows/g5-state-common.ps1')
Invoke-G5State -Action test -PythonExecutable $PythonExecutable -BaselineRunId $BaselineRunId -BuildRunId $BuildRunId
