#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PythonExecutable,
    [Parameter(Mandatory=$true)][string]$RunId
)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
& $PythonExecutable -I -B -X utf8 (Join-Path $root 'scripts/g3_integration/finish.py') --root $root --run-id $RunId
if($LASTEXITCODE -ne 0) { throw 'G3 GUI close failed; see the run evidence.' }
