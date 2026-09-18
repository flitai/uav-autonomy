#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,
      [Parameter(Mandatory=$true)][string]$BuildRunId,
      [Parameter(Mandatory=$true)][string]$ValidationRunId)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../scripts/windows/uxas-runtime-common.ps1')
Invoke-UxasRuntimeTask -Mode test -PythonExecutable $PythonExecutable -BuildRunId $BuildRunId -ValidationRunId $ValidationRunId
