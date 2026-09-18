#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'uxas-build-common.ps1')
Invoke-UxasBuildTask -Mode build -PythonExecutable $PythonExecutable
