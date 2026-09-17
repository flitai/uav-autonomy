#requires -Version 5.1
[CmdletBinding()]
param([string]$PythonExecutable)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'amase-common.ps1')
Invoke-AmaseEntry -PythonExecutable $PythonExecutable -EntryArguments @('build')
