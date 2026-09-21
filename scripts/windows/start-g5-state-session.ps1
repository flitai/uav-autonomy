#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,[Parameter(Mandatory=$true)][string]$BuildRunId,
      [string]$BaselineRunId,[ValidateSet('Headless','Gui')][string]$Mode='Gui')
. (Join-Path $PSScriptRoot 'g5-state-common.ps1')
Invoke-G5State -Action session -PythonExecutable $PythonExecutable -BaselineRunId $BaselineRunId -BuildRunId $BuildRunId -Mode $Mode
