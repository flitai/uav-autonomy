param([Parameter(Mandatory=$true)][string]$PythonExecutable, [Parameter(Mandatory=$true)][string]$BuildRunId, [string]$BaselineRunId)
. (Join-Path $PSScriptRoot '../../scripts/windows/g5-map-common.ps1')
Invoke-G5Map -Action test -PythonExecutable $PythonExecutable -BuildRunId $BuildRunId -BaselineRunId $BaselineRunId
