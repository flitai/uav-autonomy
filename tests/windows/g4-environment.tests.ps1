#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,[Parameter(Mandatory=$true)][string]$BaselineRunId)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
if(-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) { throw 'Explicit Python executable required.' }
& $PythonExecutable -I -B -X utf8 (Join-Path $root 'tests/g4_environment/checks.py') --root $root --baseline-run-id $BaselineRunId
exit $LASTEXITCODE
