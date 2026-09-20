param([Parameter(Mandatory=$true)][string]$PythonExecutable, [Parameter(Mandatory=$true)][string]$BuildRunId)
. (Join-Path $PSScriptRoot '../../scripts/windows/g5-geography-common.ps1')
Invoke-G5Geography -Action test -PythonExecutable $PythonExecutable -BuildRunId $BuildRunId
