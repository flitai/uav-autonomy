#requires -Version 5.1
. (Join-Path $PSScriptRoot 'uxas-build-common.ps1')

function Invoke-UxasRuntimeTask {
    param([ValidateSet('run','test')][string]$Mode,[string]$PythonExecutable,
          [string]$BuildRunId,[string]$ValidationRunId)
    $root=$script:CppProjectRoot
    $runId='g2-t06-'+$Mode+'-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff')
    $run=Join-Path $root "out/runs/$runId"
    New-Item -ItemType Directory -Path $run | Out-Null
    $before=Get-CppEnvironment; $location=Get-Location; $encoding=[Console]::OutputEncoding
    $record=[ordered]@{schemaVersion=1;runId=$runId;mode=$Mode;status='running';started=(Get-Date -Format o);invocationDirectory=$location.Path}
    $persistent=@{}; foreach($scope in @('User','Machine')) { $persistent[$scope]=[Environment]::GetEnvironmentVariable('PATH',$scope) }
    try {
        if(-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) { throw 'Explicit verified Python executable required.' }
        [Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
        foreach($name in @('PYTHONPATH','PYTHONHOME','CLASSPATH','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS')) {
            [Environment]::SetEnvironmentVariable($name,$null,'Process')
        }
        $candidate=Resolve-UxasCandidate -PythonExecutable $PythonExecutable -BuildRunId $BuildRunId -ValidationRunId $ValidationRunId
        $record.candidate=$candidate
        $arguments=@('-I','-B','-X','utf8',(Join-Path $root 'scripts/uxas_runtime/run.py'),$Mode,
                     '--root',$root,'--run-id',$runId,'--candidate',$candidate,
                     '--build-run-id',$BuildRunId,'--validation-run-id',$ValidationRunId)
        & $PythonExecutable @arguments | ForEach-Object { Write-Host $_ }
        if($LASTEXITCODE -ne 0) { throw "UxAS HelloWorld $Mode failed; see $run/result.json" }
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
        if(-not $restored) { $record.status='failed'; $record.error='UxAS runtime entry environment restoration failed.' }
        $record.finished=Get-Date -Format o
        Write-CppJson $record (Join-Path $run 'entry-result.json')
        if(-not $restored) { throw $record.error }
    }
}
