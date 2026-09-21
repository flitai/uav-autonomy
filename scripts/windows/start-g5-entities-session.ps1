[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,[Parameter(Mandatory=$true)][string]$BuildRunId,[string]$BaselineRunId,[ValidateSet('Gui','Headless')][string]$Mode='Gui')
. (Join-Path $PSScriptRoot 'g5-entities-common.ps1')
Invoke-G5Entities -Action session -PythonExecutable $PythonExecutable -BaselineRunId $BaselineRunId -BuildRunId $BuildRunId -Mode $Mode
