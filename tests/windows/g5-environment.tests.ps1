param([Parameter(Mandatory=$true)][string]$PythonExecutable, [string]$BaselineRunId)
. (Join-Path $PSScriptRoot '../../scripts/windows/g5-common.ps1')
Invoke-G5Environment -Action test -PythonExecutable $PythonExecutable -BaselineRunId $BaselineRunId
