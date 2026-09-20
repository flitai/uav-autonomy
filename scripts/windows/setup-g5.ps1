param([Parameter(Mandatory=$true)][string]$PythonExecutable, [string]$BaselineRunId, [switch]$VerifyOnly)
. (Join-Path $PSScriptRoot 'g5-common.ps1')
$action = if ($VerifyOnly) { 'verify' } else { 'setup' }
Invoke-G5Environment -Action $action -PythonExecutable $PythonExecutable -BaselineRunId $BaselineRunId
