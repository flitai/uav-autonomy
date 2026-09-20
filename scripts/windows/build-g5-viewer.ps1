param([Parameter(Mandatory=$true)][string]$PythonExecutable, [string]$BaselineRunId, [switch]$ChinesePath)
. (Join-Path $PSScriptRoot 'g5-common.ps1')
Invoke-G5Environment -Action build -PythonExecutable $PythonExecutable -BaselineRunId $BaselineRunId -ChinesePath:$ChinesePath
