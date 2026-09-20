Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-G5Map {
    param([string]$Action, [string]$PythonExecutable, [string]$BaselineRunId, [string]$BuildRunId, [switch]$ChinesePath, [switch]$Development)
    $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
    $runId = 'g5-t03-' + $Action + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
    $runDirectory = Join-Path $repoRoot ('out/runs/' + $runId)
    if (Test-Path -LiteralPath $runDirectory) { throw 'Run identity already exists' }
    New-Item -ItemType Directory -Path $runDirectory | Out-Null
    $before = [Environment]::GetEnvironmentVariables('Process')
    $locationBefore = Get-Location
    $record = [ordered]@{ task='G5-T03'; runId=$runId; action=$Action; status='running'; invokedFrom=$locationBefore.Path }
    try {
        if (-not [IO.Path]::IsPathRooted($PythonExecutable) -or -not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) { throw 'Explicit Python executable required' }
        if (-not $BaselineRunId) {
            $baselineOutput = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoRoot 'scripts/windows/check-g3-baseline.ps1') -PythonExecutable $PythonExecutable 2>&1
            $baselineExit = $LASTEXITCODE
            $baselineOutput | Out-File -LiteralPath (Join-Path $runDirectory 'baseline.log') -Encoding utf8
            if ($baselineExit -ne 0) { throw 'Current backend qualification failed; see baseline.log' }
            $ids = @($baselineOutput | ForEach-Object { if ("$_" -match '^G3_T01_RUN_ID=(.+)$') { $Matches[1] } })
            if ($ids.Count -ne 1) { throw 'Missing backend qualification identity' }
            $BaselineRunId = $ids[0]
        }
        $arguments = @('-I','-B','-X','utf8',(Join-Path $repoRoot 'scripts/g5_map/manage.py'),'--action',$Action,'--run-id',$runId,'--baseline-run-id',$BaselineRunId)
        if ($BuildRunId) { $arguments += @('--build-run-id',$BuildRunId) }
        if ($ChinesePath) { $arguments += '--chinese-path' }
        if ($Development) { $arguments += '--development' }
        & $PythonExecutable @arguments
        if ($LASTEXITCODE -ne 0) { throw 'G5 map entry failed; see result.json' }
        $record.status = 'passed'
    } catch {
        $record.status='failed'; $record.error=$_.Exception.Message; Write-Host $record.error
    } finally {
        $after = [Environment]::GetEnvironmentVariables('Process')
        $same = $before.Count -eq $after.Count
        foreach ($key in $before.Keys) { if ($after[$key] -cne $before[$key]) { $same=$false } }
        $record.environmentUnchanged=$same
        $record.locationUnchanged=(Get-Location).Path -eq $locationBefore.Path
        if (-not $same -or -not $record.locationUnchanged) { $record.status='failed' }
        [IO.File]::WriteAllText((Join-Path $runDirectory 'entry-result.json'),($record | ConvertTo-Json -Depth 8),(New-Object Text.UTF8Encoding $false))
        Write-Host ('G5_T03_RUN_ID=' + $runId)
    }
    if ($record.status -ne 'passed') { exit 1 }
}
