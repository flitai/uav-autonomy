param([Parameter(Mandatory=$true)][string]$PythonExecutable,
      [Parameter(Mandatory=$true)][string]$BuildRunId, [string]$BaselineRunId)
. (Join-Path $PSScriptRoot 'g5-common.ps1')
Invoke-G5Environment -Action serve -PythonExecutable $PythonExecutable -BaselineRunId $BaselineRunId -BuildRunId $BuildRunId
