[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,
      [Parameter(Mandatory=$true)][string]$BuildRunId,
      [Parameter(Mandatory=$true)][string]$LifecycleRunId,
      [string]$BaselineRunId)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$runId='g5-t09-test-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff')
$directory=Join-Path $root ('out/runs/'+$runId)
New-Item -ItemType Directory -Path $directory | Out-Null
$before=[Environment]::GetEnvironmentVariables('Process')
$locationBefore=Get-Location
$record=[ordered]@{task='G5-T09';runId=$runId;status='running';buildRunId=$BuildRunId;lifecycleRunId=$LifecycleRunId}
try {
    if (-not [IO.Path]::IsPathRooted($PythonExecutable) -or -not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {throw 'Explicit Python required'}
    if (-not $BaselineRunId) {
        $output=& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'scripts/windows/check-g3-baseline.ps1') -PythonExecutable $PythonExecutable 2>&1
        $code=$LASTEXITCODE;$output | Out-File -LiteralPath (Join-Path $directory 'baseline.log') -Encoding utf8
        if ($code -ne 0) {throw 'Backend source check failed'}
        $ids=@($output | ForEach-Object {if ("$_" -match '^G3_T01_RUN_ID=(.+)$') {$Matches[1]}})
        if ($ids.Count -ne 1) {throw 'Baseline identity missing'}
        $BaselineRunId=$ids[0]
    }
    & $PythonExecutable -I -B -X utf8 (Join-Path $root 'scripts/g5_full/manage.py') --run-id $runId --baseline-run-id $BaselineRunId --build-run-id $BuildRunId --lifecycle-run-id $LifecycleRunId
    if ($LASTEXITCODE -ne 0) {throw 'G5-T09 failed; inspect result.json'}
    $record.status='passed'
} catch {$record.status='failed';$record.error=$_.Exception.Message;Write-Host $record.error}
finally {
    $after=[Environment]::GetEnvironmentVariables('Process');$same=$before.Count -eq $after.Count
    foreach ($key in $before.Keys) {if ($after[$key] -cne $before[$key]) {$same=$false}}
    $record.environmentUnchanged=$same;$record.locationUnchanged=(Get-Location).Path -eq $locationBefore.Path
    if (-not $same -or -not $record.locationUnchanged) {$record.status='failed'}
    [IO.File]::WriteAllText((Join-Path $directory 'entry-result.json'),($record|ConvertTo-Json -Depth 8),(New-Object Text.UTF8Encoding $false))
    Write-Host ('G5_T09_RUN_ID='+$runId)
}
if ($record.status -ne 'passed') {exit 1}
