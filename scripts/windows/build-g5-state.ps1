#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,[string]$BaselineRunId,[switch]$ChinesePath)
. (Join-Path $PSScriptRoot 'g5-state-common.ps1')
Invoke-G5State -Action build -PythonExecutable $PythonExecutable -BaselineRunId $BaselineRunId -ChinesePath:$ChinesePath
