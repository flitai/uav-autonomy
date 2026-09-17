#requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Gui','Headless')][string]$Mode = 'Gui',
    [string]$Scenario,
    [ValidateRange(1,65535)][int]$Port = 5555,
    [ValidateRange(0,50000)][int]$EntityPortOffset = 0,
    [ValidateRange(0.1,100)][double]$SimRate = 0,
    [string]$BuildRunId,
    [switch]$ValidateRun,
    [string]$PythonExecutable
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'amase-common.ps1')
if (-not $PSBoundParameters.ContainsKey('SimRate')) { $SimRate = if ($Mode -eq 'Gui') { 1 } else { 20 } }
$arguments = @('run','--mode',$Mode.ToLowerInvariant(),'--port',[string]$Port,'--sim-rate',$SimRate.ToString([Globalization.CultureInfo]::InvariantCulture))
$arguments += @('--entity-port-offset',[string]$EntityPortOffset)
if ($Scenario) { $arguments += @('--scenario',[IO.Path]::GetFullPath($Scenario)) }
if ($BuildRunId) { $arguments += @('--build-run-id',$BuildRunId) }
if ($ValidateRun) { $arguments += '--validate-run' }
Invoke-AmaseEntry -PythonExecutable $PythonExecutable -EntryArguments $arguments
