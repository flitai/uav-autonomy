#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,
      [Parameter(Mandatory=$true)][string]$BuildRunId,
      [Parameter(Mandatory=$true)][string]$ValidationRunId,
      [Parameter(Mandatory=$true)][string]$HelloWorldRunId)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../scripts/windows/uxas-release-common.ps1')
Invoke-UxasReleaseTask -Mode test -PythonExecutable $PythonExecutable -BuildRunId $BuildRunId -ValidationRunId $ValidationRunId -HelloWorldRunId $HelloWorldRunId
