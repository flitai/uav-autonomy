#requires -Version 5.1
. (Join-Path $PSScriptRoot 'uxas-build-common.ps1')

function Invoke-UxasReleaseTask {
    param([ValidateSet('test','publish','run','resolve')][string]$Mode,[string]$PythonExecutable,
          [string]$BuildRunId,[string]$ValidationRunId,[string]$HelloWorldRunId,[string]$ReleaseRunId)
    $root=$script:CppProjectRoot
    $runId='g2-t07-'+$Mode+'-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff')
    $run=Join-Path $root "out/runs/$runId"
    New-Item -ItemType Directory -Path $run | Out-Null
    $before=Get-CppEnvironment; $location=Get-Location; $encoding=[Console]::OutputEncoding
    $record=[ordered]@{schemaVersion=1;runId=$runId;mode=$Mode;status='running';started=(Get-Date -Format o);invocationDirectory=$location.Path}
    $persistent=@{}; foreach($scope in @('User','Machine')) { $persistent[$scope]=[Environment]::GetEnvironmentVariable('PATH',$scope) }
    $worker=Join-Path $root 'scripts/uxas_release/release.py'
    try {
        if(-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) { throw 'Explicit verified Python executable required.' }
        [Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
        foreach($name in @('PYTHONPATH','PYTHONHOME','CLASSPATH','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS')) {
            [Environment]::SetEnvironmentVariable($name,$null,'Process')
        }
        if($Mode -eq 'publish') {
            if($ReleaseRunId -notmatch '^g2-t07-test-[0-9-]+$') { throw 'Invalid release validation ID.' }
            $receiptPath=Get-CppChildPath (Join-Path $root 'out/runs') ($ReleaseRunId+'/acceptance.json')
            $receipt=Get-Content -Raw -Encoding UTF8 $receiptPath | ConvertFrom-Json
            $BuildRunId=$receipt.provenance.buildRunId; $ValidationRunId=$receipt.provenance.validationRunId
        } elseif($Mode -in @('run','resolve')) {
            $pointer=Get-Content -Raw -Encoding UTF8 (Join-Path $root 'out/artifacts/uxas/current.json') | ConvertFrom-Json
            $BuildRunId=$pointer.buildRunId; $ValidationRunId=$pointer.validationRunId
        }
        $candidate=Resolve-UxasCandidate -PythonExecutable $PythonExecutable -BuildRunId $BuildRunId -ValidationRunId $ValidationRunId
        $arguments=@('-I','-B','-X','utf8',$worker,$Mode,'--root',$root,'--run-id',$runId,
                     '--build-run-id',$BuildRunId,'--validation-run-id',$ValidationRunId)
        if($HelloWorldRunId) { $arguments+=@('--hello-world-run-id',$HelloWorldRunId) }
        if($ReleaseRunId) { $arguments+=@('--release-run-id',$ReleaseRunId) }
        & $PythonExecutable @arguments | ForEach-Object { Write-Host $_ }
        if($LASTEXITCODE -ne 0) { throw "UxAS release $Mode failed; see $run/result.json" }
        $record.status='passed'
    } catch { $record.status='failed'; $record.error=$_.Exception.Message; throw }
    finally {
        Restore-CppEnvironment $before
        Set-Location -LiteralPath $location.Path; [Console]::OutputEncoding=$encoding
        $after=Get-CppEnvironment
        $record.environmentRestored=(@(Compare-Object @($before.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) @($after.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" })).Count -eq 0)
        $record.locationRestored=((Get-Location).Path -ceq $location.Path)
        $record.encodingRestored=([Console]::OutputEncoding.CodePage -eq $encoding.CodePage)
        $record.persistentPathUnchanged=$true
        foreach($scope in @('User','Machine')) { if($persistent[$scope] -cne [Environment]::GetEnvironmentVariable('PATH',$scope)) { $record.persistentPathUnchanged=$false } }
        $restored=$record.environmentRestored -and $record.locationRestored -and $record.encodingRestored -and $record.persistentPathUnchanged
        if(-not $restored) { $record.status='failed'; $record.error='Release entry restoration failed.' }
        $record.finished=Get-Date -Format o
        Write-CppJson $record (Join-Path $run 'entry-result.json')
        if(-not $restored) { throw $record.error }
    }
    # Only an already restored, successful entry may switch the qualified pointer.
    if($Mode -eq 'publish') {
        & $PythonExecutable -I -B -X utf8 $worker commit --root $root --run-id $runId | ForEach-Object { Write-Host $_ }
        if($LASTEXITCODE -ne 0) {
            $record.status='failed'; $record.error='Publication commit failed; prior pointer preserved.'
            Write-CppJson $record (Join-Path $run 'entry-result.json')
            throw $record.error
        }
    }
}

function Resolve-UxasPackage {
    param([Parameter(Mandatory=$true)][string]$PythonExecutable)
    Invoke-UxasReleaseTask -Mode resolve -PythonExecutable $PythonExecutable
    $pointer=Get-Content -Raw -Encoding UTF8 (Join-Path $script:CppProjectRoot 'out/artifacts/uxas/current.json') | ConvertFrom-Json
    return Get-CppChildPath (Join-Path $script:CppProjectRoot 'out/artifacts/uxas') $pointer.path
}
