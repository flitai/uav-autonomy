#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,
      [Parameter(Mandatory=$true)][string]$BuildRunId,
      [Parameter(Mandatory=$true)][string]$FlightRunId, [string]$BaselineRunId)
. (Join-Path $PSScriptRoot '../../scripts/windows/g5-backend-common.ps1')
Invoke-G5Backend -Action test -PythonExecutable $PythonExecutable -BuildRunId $BuildRunId -FlightRunId $FlightRunId -BaselineRunId $BaselineRunId
