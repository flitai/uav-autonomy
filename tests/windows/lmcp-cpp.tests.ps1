#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,
      [Parameter(Mandatory=$true)][string]$BuildRunId)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../scripts/windows/lmcp-cpp-common.ps1')
Invoke-LmcpCppTask -Mode test -PythonExecutable $PythonExecutable -BuildRunId $BuildRunId
