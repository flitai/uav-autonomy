#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable, [string]$BaselineRunId)
. (Join-Path $PSScriptRoot 'g5-backend-common.ps1')
Invoke-G5Backend -Action prepare -PythonExecutable $PythonExecutable -BaselineRunId $BaselineRunId
