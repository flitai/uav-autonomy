#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,
      [Parameter(Mandatory=$true)][string]$ReleaseRunId)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'uxas-release-common.ps1')
Invoke-UxasReleaseTask -Mode publish -PythonExecutable $PythonExecutable -ReleaseRunId $ReleaseRunId
