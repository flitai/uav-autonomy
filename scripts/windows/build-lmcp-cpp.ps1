#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'lmcp-cpp-common.ps1')
Invoke-LmcpCppTask -Mode build -PythonExecutable $PythonExecutable
