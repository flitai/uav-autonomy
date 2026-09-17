#requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Automatic','Finalize')][string]$Action = 'Automatic',
    [string]$ValidationRunId,
    [string]$ManualConfirmation,
    [string]$PythonExecutable
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../../scripts/windows/tcp-common.ps1')
$arguments = @($Action.ToLowerInvariant())
if ($ValidationRunId) { $arguments += @('--validation-run-id',$ValidationRunId) }
if ($ManualConfirmation) { $arguments += @('--manual-confirmation',$ManualConfirmation) }
Invoke-AmaseTcpEntry -PythonExecutable $PythonExecutable -EntryArguments $arguments
