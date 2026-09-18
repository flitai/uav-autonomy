#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,
      [Parameter(Mandatory=$true)][string]$ConfigureRunId)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../scripts/windows/uxas-cmake-common.ps1')
Invoke-UxasCMakeTask -Mode test -PythonExecutable $PythonExecutable -ConfigureRunId $ConfigureRunId
