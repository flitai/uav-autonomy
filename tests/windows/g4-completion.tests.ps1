#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,[string]$BaselineRunId)
$ErrorActionPreference='Stop'
$arguments=@('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot '../../scripts/windows/run-g4-completion.ps1'),'-PythonExecutable',$PythonExecutable,'-Verify')
if($BaselineRunId) { $arguments+=@('-BaselineRunId',$BaselineRunId) }
& powershell.exe @arguments
exit $LASTEXITCODE
