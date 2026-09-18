#requires -Version 5.1
. (Join-Path $PSScriptRoot 'lmcp-cpp-common.ps1')

function Invoke-UxasCMakeTask {
    param([ValidateSet('configure','test')][string]$Mode,[string]$PythonExecutable,[string]$ConfigureRunId)
    $root=$script:CppProjectRoot
    $runId='g2-t04-'+$Mode+'-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff')
    $run=Join-Path $root "out/runs/$runId"
    New-Item -ItemType Directory -Path $run -Force | Out-Null
    $before=Get-CppEnvironment; $location=Get-Location; $encoding=[Console]::OutputEncoding
    $record=[ordered]@{schemaVersion=1;runId=$runId;mode=$Mode;status='running';started=(Get-Date -Format o)}
    $persistent=@{}; foreach($scope in @('User','Machine')) { $persistent[$scope]=[Environment]::GetEnvironmentVariable('PATH',$scope) }
    try {
        if(-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) { throw 'Explicit verified Python executable required.' }
        [Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
        foreach($name in @('PYTHONPATH','PYTHONHOME','CLASSPATH','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS')) {
            [Environment]::SetEnvironmentVariable($name,$null,'Process')
        }
        $cfg=Read-CppConfig
        $tools=Set-CppProcessEnvironment $cfg $root $run
        $record.versions=Test-CppToolVersions $cfg $tools $root $run
        $deps=Resolve-DepsPackage
        $lmcp=Resolve-LmcpCppPackage -PythonExecutable $PythonExecutable
        $context=@{tools=$tools;dependencies=$deps;lmcp=$lmcp;include=$env:INCLUDE;lib=$env:LIB;libpath=$env:LIBPATH}
        $contextFile=Join-Path $run 'context.json'; Write-CppJson $context $contextFile
        $arguments=@('-I','-B','-X','utf8',(Join-Path $root 'scripts/uxas/graph.py'),$Mode,'--root',$root,'--run-id',$runId,'--context',$contextFile)
        if($ConfigureRunId) { $arguments+=@('--configure-run-id',$ConfigureRunId) }
        & $PythonExecutable @arguments | ForEach-Object { Write-Host $_ }
        if($LASTEXITCODE -ne 0) { throw "UxAS CMake $Mode failed; see $run/result.json" }
        $record.status='passed'
    } catch { $record.status='failed'; $record.error=$_.Exception.Message; throw }
    finally {
        Restore-CppEnvironment $before
        Set-Location -LiteralPath $location.Path; [Console]::OutputEncoding=$encoding
        $after=Get-CppEnvironment
        $record.environmentRestored=(@(Compare-Object @($before.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) @($after.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" })).Count -eq 0)
        $record.persistentPathUnchanged=$true
        foreach($scope in @('User','Machine')) { if($persistent[$scope] -cne [Environment]::GetEnvironmentVariable('PATH',$scope)) { $record.persistentPathUnchanged=$false } }
        $record.finished=Get-Date -Format o
        Write-CppJson $record (Join-Path $run 'entry-result.json')
        if(-not $record.environmentRestored -or -not $record.persistentPathUnchanged) { throw 'UxAS entry environment restoration failed.' }
    }
}
