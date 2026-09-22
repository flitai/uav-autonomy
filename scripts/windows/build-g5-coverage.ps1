[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,[string]$BaselineRunId,[switch]$ChinesePath)
. (Join-Path $PSScriptRoot 'g5-coverage-common.ps1')
Invoke-G5Coverage -Action build -PythonExecutable $PythonExecutable -BaselineRunId $BaselineRunId -ChinesePath:$ChinesePath
