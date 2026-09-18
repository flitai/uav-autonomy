#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'uxas-cmake-common.ps1')
Invoke-UxasCMakeTask -Mode configure -PythonExecutable $PythonExecutable
