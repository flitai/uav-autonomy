#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,[switch]$VerifyOnly)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'cpp-common.ps1')
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$runId='g5-t06-model-tools-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff')
$run=Join-Path $root ('out/runs/'+$runId)
New-Item -ItemType Directory -Path $run | Out-Null
$before=Get-CppEnvironment; $locationBefore=Get-Location
$record=[ordered]@{task='G5-T06-model-tools';runId=$runId;status='running'}
try {
    if (-not [IO.Path]::IsPathRooted($PythonExecutable) -or -not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {throw 'Explicit Python required'}
    $config=Read-CppConfig; $tools=Set-CppProcessEnvironment $config
    $null=Test-CppToolVersions $config $tools $root
    $arguments=@('-I','-B','-X','utf8',(Join-Path $root 'scripts/g5_models/tools.py'),'--run-id',$runId,'--cmake',$tools.cmake,'--ninja',$tools.ninja)
    if ($VerifyOnly) {$arguments+='--verify'}
    & $PythonExecutable @arguments
    if ($LASTEXITCODE -ne 0) {throw 'Model tools failed; inspect result.json'}
    $record.status='passed'
} catch {$record.status='failed';$record.error=$_.Exception.Message;Write-Host $record.error}
finally {
    Restore-CppEnvironment $before
    $after=Get-CppEnvironment; $same=$before.Count -eq $after.Count
    foreach ($key in $before.Keys) {if ($before[$key] -cne $after[$key]) {$same=$false}}
    $record.environmentUnchanged=$same
    $record.locationUnchanged=(Get-Location).Path -eq $locationBefore.Path
    if (-not $same -or -not $record.locationUnchanged) {$record.status='failed'}
    [IO.File]::WriteAllText((Join-Path $run 'entry-result.json'),($record|ConvertTo-Json -Depth 8),(New-Object Text.UTF8Encoding $false))
    Write-Host ('G5_MODEL_TOOLS_RUN_ID='+$runId)
}
if ($record.status -ne 'passed' -or -not $record.locationUnchanged) {exit 1}
