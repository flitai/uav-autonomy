param([Parameter(Mandatory=$true)][string]$PythonExecutable, [Parameter(Mandatory=$true)][string]$BuildRunId,
      [string]$BaselineRunId, [switch]$Development)
. (Join-Path $PSScriptRoot 'g5-map-common.ps1')
Invoke-G5Map -Action serve -PythonExecutable $PythonExecutable -BuildRunId $BuildRunId -BaselineRunId $BaselineRunId -Development:$Development
