param([Parameter(Mandatory=$true)][string]$PythonExecutable)
. (Join-Path $PSScriptRoot 'g5-geography-common.ps1')
Invoke-G5Geography -Action prepare -PythonExecutable $PythonExecutable
