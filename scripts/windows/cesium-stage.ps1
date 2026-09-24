[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('Build','Qualify','Review','Confirm','Publish','Run')][string]$Action,
    [Parameter(Mandatory=$true)][string]$PythonExecutable,
    [string]$BaselineRunId,
    [string]$CoverageBuildRunId,
    [string]$FullRunId,
    [string]$ScaleRunId,
    [string]$StageBuildRunId,
    [string]$QualificationRunId,
    [string]$ReviewRunId,
    [ValidateSet('approve','reject')][string]$Decision,
    [string]$Note,
    [switch]$AutoStop
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$prefix=@{Build='cesium-stage-build';Qualify='cesium-stage-test';Review='cesium-stage-review';Confirm='cesium-stage-confirm';Publish='cesium-stage-publish';Run='cesium-stage-run'}[$Action]
$runId=$prefix+'-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff')
$directory=Join-Path $root ('out/runs/'+$runId)
New-Item -ItemType Directory -Path $directory | Out-Null
$before=[Environment]::GetEnvironmentVariables('Process')
$locationBefore=Get-Location
$record=[ordered]@{task='G5-T11';action=$Action;runId=$runId;status='running'}
try {
    if (-not [IO.Path]::IsPathRooted($PythonExecutable) -or -not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {throw 'Explicit Python required'}
    if ($Action -ne 'Confirm' -and (-not $BaselineRunId -or -not $CoverageBuildRunId -or -not $FullRunId -or -not $ScaleRunId)) {
        throw 'Explicit baseline, coverage build, full run and scale run IDs required'
    }
    if ($Action -in @('Qualify','Review','Publish','Run') -and -not $StageBuildRunId) {throw 'Stage build ID required'}
    if ($Action -in @('Review','Publish','Run') -and -not $QualificationRunId) {throw 'Stage qualification ID required'}
    if ($Action -eq 'Publish' -and -not $ReviewRunId) {throw 'Current review ID required'}
    if ($Action -eq 'Confirm' -and (-not $ReviewRunId -or -not $Decision)) {throw 'Review ID and decision required'}
    $arguments=@('-I','-B','-X','utf8',(Join-Path $root 'scripts/g5_stage/manage.py'),'--action',$Action.ToLowerInvariant(),'--run-id',$runId)
    foreach ($item in @(@('baseline-run-id',$BaselineRunId),@('coverage-build-run-id',$CoverageBuildRunId),@('full-run-id',$FullRunId),@('scale-run-id',$ScaleRunId),@('stage-build-run-id',$StageBuildRunId),@('qualification-run-id',$QualificationRunId),@('review-run-id',$ReviewRunId),@('decision',$Decision),@('note',$Note))) {
        if ($item[1]) {$arguments+=('--'+$item[0]);$arguments+=$item[1]}
    }
    if ($AutoStop) {$arguments+='--auto-stop'}
    & $PythonExecutable @arguments
    if ($LASTEXITCODE -ne 0) {throw 'G5-T11 action failed; inspect result.json'}
    $record.status='passed'
} catch {$record.status='failed';$record.error=$_.Exception.Message;Write-Host $record.error}
finally {
    $after=[Environment]::GetEnvironmentVariables('Process');$same=$before.Count -eq $after.Count
    foreach ($key in $before.Keys) {if ($after[$key] -cne $before[$key]) {$same=$false}}
    $record.environmentUnchanged=$same;$record.locationUnchanged=(Get-Location).Path -eq $locationBefore.Path
    if (-not $same -or -not $record.locationUnchanged) {$record.status='failed'}
    [IO.File]::WriteAllText((Join-Path $directory 'entry-result.json'),($record|ConvertTo-Json -Depth 8),(New-Object Text.UTF8Encoding $false))
    Write-Host ('G5_T11_RUN_ID='+$runId)
}
if ($record.status -ne 'passed') {exit 1}
