#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$AmaseRunId,
    [string]$PythonExecutable
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'tcp-common.ps1')
Invoke-AmaseTcpEntry -PythonExecutable $PythonExecutable -EntryArguments @('receive','--amase-run-id',$AmaseRunId)
