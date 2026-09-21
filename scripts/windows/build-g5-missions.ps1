[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,[string]$BaselineRunId,[switch]$ChinesePath)
. (Join-Path $PSScriptRoot 'g5-missions-common.ps1')
Invoke-G5Missions -Action build -PythonExecutable $PythonExecutable -BaselineRunId $BaselineRunId -ChinesePath:$ChinesePath
