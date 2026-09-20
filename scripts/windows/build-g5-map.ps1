param([Parameter(Mandatory=$true)][string]$PythonExecutable, [string]$BaselineRunId, [switch]$ChinesePath)
. (Join-Path $PSScriptRoot 'g5-map-common.ps1')
Invoke-G5Map -Action build -PythonExecutable $PythonExecutable -BaselineRunId $BaselineRunId -ChinesePath:$ChinesePath
