#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,
      [Parameter(Mandatory=$true)][string]$BuildRunId,
      [Parameter(Mandatory=$true)][string]$ValidationRunId,
      [ValidateSet('HelloWorld')][string]$Example='HelloWorld')
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'uxas-runtime-common.ps1')
Invoke-UxasRuntimeTask -Mode run -PythonExecutable $PythonExecutable -BuildRunId $BuildRunId -ValidationRunId $ValidationRunId
