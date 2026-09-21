[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,[Parameter(Mandatory=$true)][string]$BuildRunId,[string]$BaselineRunId)
. (Join-Path $PSScriptRoot '../../scripts/windows/g5-missions-common.ps1')
Invoke-G5Missions -Action test -PythonExecutable $PythonExecutable -BaselineRunId $BaselineRunId -BuildRunId $BuildRunId
