#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,
      [Parameter(Mandatory=$true)][string]$BuildRunId,
      [string]$BaselineRunId, [ValidateSet('Headless','Gui','Both')][string]$Mode='Both')
. (Join-Path $PSScriptRoot 'g5-backend-common.ps1')
Invoke-G5Backend -Action run -PythonExecutable $PythonExecutable -BuildRunId $BuildRunId -BaselineRunId $BaselineRunId -Mode $Mode
