#requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Automatic','Finalize')][string]$Action = 'Automatic',
    [Parameter(Mandatory=$true)][string]$BuildRunId,
    [string]$GuiRunId,
    [string]$ValidationRunId,
    [string]$ManualConfirmation,
    [string]$PythonExecutable
)
$ErrorActionPreference = 'Stop'
$environmentBefore = foreach ($scope in @('Process','User','Machine')) {
    foreach ($name in @('JAVA_HOME','ANT_HOME','PATH','JAVACMD','CLASSPATH','ANT_ARGS','ANT_OPTS',
            'JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','PYTHONPATH','PYTHONHOME')) {
        [pscustomobject]@{scope=$scope;name=$name;value=[Environment]::GetEnvironmentVariable($name,$scope)}
    }
}
$policyBefore = Get-ExecutionPolicy -List | ConvertTo-Json -Compress
. (Join-Path $PSScriptRoot '../../scripts/windows/amase-common.ps1')
$arguments = @($Action.ToLowerInvariant(),'--build-run-id',$BuildRunId)
if ($GuiRunId) { $arguments += @('--gui-run-id',$GuiRunId) }
if ($ValidationRunId) { $arguments += @('--validation-run-id',$ValidationRunId) }
if ($ManualConfirmation) { $arguments += @('--manual-confirmation',$ManualConfirmation) }
Invoke-AmaseEntry -PythonExecutable $PythonExecutable -EntryArguments $arguments
foreach ($item in $environmentBefore) {
    if ([Environment]::GetEnvironmentVariable($item.name,$item.scope) -cne $item.value) {
        throw "Environment changed: $($item.scope)/$($item.name)"
    }
}
if ((Get-ExecutionPolicy -List | ConvertTo-Json -Compress) -cne $policyBefore) { throw 'Execution policy changed.' }
Write-Host 'PASS: 36 environment values and execution policies unchanged.'
