#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,
      [ValidateSet('HelloWorld')][string]$Example='HelloWorld')
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'uxas-release-common.ps1')
Invoke-UxasReleaseTask -Mode run -PythonExecutable $PythonExecutable
