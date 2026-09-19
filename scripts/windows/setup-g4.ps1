#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PythonExecutable,
    [string]$BaselineRunId,
    [string]$RunId,
    [switch]$VerifyOnly
)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
if(-not $RunId) { $RunId='g4-t01-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff') }
if($RunId -notmatch '^g4-t01-[A-Za-z0-9-]{1,80}$') { throw 'Invalid G4 run identity.' }
$run=Join-Path $root ('out/runs/'+$RunId)
if(Test-Path -LiteralPath $run) { throw 'Run already exists; cannot overwrite evidence.' }
New-Item -ItemType Directory -Path $run | Out-Null
$location=(Get-Location).Path
$before=@{}; Get-ChildItem Env: | ForEach-Object { $before[$_.Name]=$_.Value }
$record=[ordered]@{task='G4-T01';runId=$RunId;status='running';invocationDirectory=$location;startedAt=(Get-Date -Format o)}
$exitCode=1
try {
    if(-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) { throw 'Explicit Python executable required.' }
    $PythonExecutable=(Resolve-Path -LiteralPath $PythonExecutable).Path
    if(-not $BaselineRunId) {
        $output=@(& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'check-g3-baseline.ps1') -PythonExecutable $PythonExecutable)
        $qualificationExit=$LASTEXITCODE
        $output | Set-Content -LiteralPath (Join-Path $run 'qualification.log') -Encoding UTF8
        if($qualificationExit -ne 0) { throw 'Current G3 input qualification failed.' }
        $ids=@($output | ForEach-Object { if($_ -match '^G3_T01_RUN_ID=(.+)$') { $Matches[1] } })
        if($ids.Count -ne 1) { throw 'Missing unique qualification identity.' }
        $BaselineRunId=$ids[0]
    }
    $arguments=@('-I','-B','-X','utf8',(Join-Path $root 'scripts/g4_environment/manage.py'),'--root',$root,'--run-id',$RunId,'--baseline-run-id',$BaselineRunId)
    if($VerifyOnly) { $arguments+='--verify-only' }
    & $PythonExecutable @arguments
    if($LASTEXITCODE -ne 0) { throw 'G4 environment failed; see result.json.' }
    $record.status='passed'; $exitCode=0
} catch {
    $record.status='failed'; $record.error=$_.Exception.Message
    Write-Host ('FAILED: '+$record.error)
} finally {
    $after=@{}; Get-ChildItem Env: | ForEach-Object { $after[$_.Name]=$_.Value }
    $record.environmentUnchanged=(@(Compare-Object @($before.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) @($after.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" })).Count -eq 0)
    $record.locationUnchanged=((Get-Location).Path -ceq $location)
    if(-not ($record.environmentUnchanged -and $record.locationUnchanged)) { $record.status='failed'; $exitCode=1 }
    $record.finishedAt=Get-Date -Format o
    [IO.File]::WriteAllText((Join-Path $run 'entry-result.json'),($record | ConvertTo-Json -Depth 20),(New-Object Text.UTF8Encoding($false)))
    Write-Host ('G4_T01_RUN_ID='+$RunId)
}
exit $exitCode
