[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,[Parameter(Mandatory=$true)][string]$BuildRunId,[string]$BaselineRunId)
. (Join-Path $PSScriptRoot '../../scripts/windows/g5-entities-common.ps1')
Invoke-G5Entities -Action test -PythonExecutable $PythonExecutable -BaselineRunId $BaselineRunId -BuildRunId $BuildRunId
