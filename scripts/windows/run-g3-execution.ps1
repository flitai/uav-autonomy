#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PythonExecutable,
    [ValidateSet('Gui','Headless')][string]$Mode='Headless',
    [string]$Configuration,
    [string]$RunId,
    [string]$BaselineRunId,
    [switch]$Verify
)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'uxas-release-common.ps1')
. (Join-Path $PSScriptRoot 'java-common.ps1')
$root=$script:CppProjectRoot
if(-not $RunId) { $RunId='g3-t04-'+$(if($Verify){'test'}else{'run'})+'-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff') }
if($RunId -notmatch '^g3-t04-[A-Za-z0-9-]{1,80}$') { throw 'Invalid G3 run identity.' }
$run=Join-Path $root ('out/runs/'+$RunId)
if(Test-Path -LiteralPath $run) { throw 'Run identity already exists; historical evidence cannot be overwritten.' }
New-Item -ItemType Directory -Path $run | Out-Null
$before=Get-CppEnvironment; $location=Get-Location; $encoding=[Console]::OutputEncoding
$persistent=@{}; foreach($scope in @('User','Machine')) { $persistent[$scope]=[Environment]::GetEnvironmentVariable('PATH',$scope) }
$record=[ordered]@{task='G3-T04';runId=$RunId;status='running';startedAt=(Get-Date -Format o);invocationDirectory=$location.Path}
try {
    if(-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) { throw 'Explicit verified Python executable required.' }
    $PythonExecutable=(Resolve-Path -LiteralPath $PythonExecutable).Path
    if(-not $Configuration) { $Configuration=Join-Path $root 'config/g3-execution.json' }
    $Configuration=(Resolve-Path -LiteralPath $Configuration).Path
    [Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
    foreach($name in @('PYTHONPATH','PYTHONHOME','CLASSPATH','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','ANT_ARGS','ANT_OPTS')) {
        [Environment]::SetEnvironmentVariable($name,$null,'Process')
    }
    if(-not $BaselineRunId) {
        $output=@(& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'check-g3-baseline.ps1') -PythonExecutable $PythonExecutable)
        $code=$LASTEXITCODE
        $output | Set-Content -LiteralPath (Join-Path $run 'qualification.log') -Encoding UTF8
        if($code -ne 0) { throw 'Fresh G3 input qualification failed.' }
        $ids=@($output | ForEach-Object { if($_ -match '^G3_T01_RUN_ID=(.+)$') { $Matches[1] } })
        if($ids.Count -ne 1) { throw 'Qualification did not return a unique identity.' }
        $BaselineRunId=$ids[0]
    }
    if($BaselineRunId -notmatch '^g3-t01-check-[0-9-]+$') { throw 'Invalid baseline identity.' }
    Set-JavaProcessEnvironment -Config (Read-JavaToolchain -ProjectRoot $root) -ProjectRoot $root
    Write-CppJson @{baselineRunId=$BaselineRunId;javaHome=$env:JAVA_HOME;configuration=(Join-Path $root 'config/g3-startup.json');executionConfiguration=$Configuration;mode=$Mode;verify=[bool]$Verify} (Join-Path $run 'context.json')
    $arguments=@('-I','-B','-X','utf8',(Join-Path $root 'scripts/g3_execution/runtime.py'),'--root',$root,'--run-id',$RunId,'--mode',$Mode)
    if($Verify) { $arguments+='--verify' }
    & $PythonExecutable @arguments
    if($LASTEXITCODE -ne 0) { throw "G3 execution failed; see $run/result.json" }
    $record.status='passed'
} catch { $record.status='failed'; $record.error=$_.Exception.Message; throw }
finally {
    Restore-CppEnvironment $before; Set-Location -LiteralPath $location.Path; [Console]::OutputEncoding=$encoding
    $after=Get-CppEnvironment
    $record.environmentRestored=(@(Compare-Object @($before.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) @($after.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" })).Count -eq 0)
    $record.locationRestored=((Get-Location).Path -ceq $location.Path)
    $record.encodingRestored=([Console]::OutputEncoding.CodePage -eq $encoding.CodePage)
    $record.persistentPathUnchanged=$true
    foreach($scope in @('User','Machine')) { if($persistent[$scope] -cne [Environment]::GetEnvironmentVariable('PATH',$scope)) { $record.persistentPathUnchanged=$false } }
    $restored=$record.environmentRestored -and $record.locationRestored -and $record.encodingRestored -and $record.persistentPathUnchanged
    if(-not $restored) { $record.status='failed'; $record.error='G3 environment restoration failed.' }
    $record.finishedAt=Get-Date -Format o
    Write-CppJson $record (Join-Path $run 'entry-result.json')
    Write-Host "G3_T04_RUN_ID=$RunId"
    if(-not $restored) { throw $record.error }
}
