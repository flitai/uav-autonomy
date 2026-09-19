#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PythonExecutable,
    [Parameter(Mandatory=$true)][string]$RunId,
    [Parameter(Mandatory=$true)][string]$ConfirmationText
)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
& $PythonExecutable -I -B -X utf8 (Join-Path $root 'scripts/g3_acceptance/finish.py') --root $root --run-id $RunId --confirmation-text $ConfirmationText
if($LASTEXITCODE -ne 0) { throw 'G3 stage confirmation/normal close failed; inspect the original receipts.' }
