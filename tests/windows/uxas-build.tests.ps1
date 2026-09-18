#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,
      [Parameter(Mandatory=$true)][string]$BuildRunId)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../scripts/windows/uxas-build-common.ps1')
Invoke-UxasBuildTask -Mode test -PythonExecutable $PythonExecutable -BuildRunId $BuildRunId
