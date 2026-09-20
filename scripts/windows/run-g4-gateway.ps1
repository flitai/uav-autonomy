#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PythonExecutable,
    [Parameter(Mandatory=$true)][string]$Manifest,
    [Parameter(Mandatory=$true)][string]$ManifestSHA256,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
& $PythonExecutable -I -B -X utf8 (Join-Path $root 'scripts/g4_stage/entry.py') --root $root observe --manifest $Manifest --manifest-sha256 $ManifestSHA256 --output $OutputDirectory
exit $LASTEXITCODE
