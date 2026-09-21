[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,[string]$BaselineRunId,[switch]$ChinesePath)
. (Join-Path $PSScriptRoot 'g5-entities-common.ps1')
Invoke-G5Entities -Action build -PythonExecutable $PythonExecutable -BaselineRunId $BaselineRunId -ChinesePath:$ChinesePath
