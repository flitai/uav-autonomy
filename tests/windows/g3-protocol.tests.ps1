#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PythonExecutable,
    [Parameter(Mandatory=$true)][string]$BaselineRunId,
    [string]$AmaseBuildRunId,
    [string]$UxasBuildRunId,
    [string]$UxasValidationRunId,
    [ValidateSet('Reproduce','Verify')][string]$Action='Verify'
)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../scripts/windows/uxas-release-common.ps1')
. (Join-Path $PSScriptRoot '../../scripts/windows/java-common.ps1')
$root=$script:CppProjectRoot
$runId='g3-t02-'+$Action.ToLower()+'-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff')
$run=Join-Path $root ('out/runs/'+$runId)
New-Item -ItemType Directory -Path $run | Out-Null
$before=Get-CppEnvironment; $location=Get-Location; $encoding=[Console]::OutputEncoding
$persistent=@{}; foreach($scope in @('User','Machine')) { $persistent[$scope]=[Environment]::GetEnvironmentVariable('PATH',$scope) }
$record=[ordered]@{runId=$runId;task='G3-T02';status='running';startedAt=(Get-Date -Format o);invocationDirectory=$location.Path}
try {
    if($BaselineRunId -notmatch '^g3-t01-check-[0-9-]+$') { throw 'Invalid baseline identity.' }
    if(-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) { throw 'Explicit verified Python executable required.' }
    $PythonExecutable=(Resolve-Path -LiteralPath $PythonExecutable).Path
    [Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
    foreach($name in @('PYTHONPATH','PYTHONHOME','CLASSPATH','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','ANT_ARGS','ANT_OPTS')) {
        [Environment]::SetEnvironmentVariable($name,$null,'Process')
    }
    $config=Read-CppConfig
    $native=Set-CppProcessEnvironment -Config $config -Root $root -LogRoot $run
    $dependencies=Resolve-DepsPackage
    Set-JavaProcessEnvironment -Config (Read-JavaToolchain -ProjectRoot $root) -ProjectRoot $root
    Write-CppJson @{baselineRunId=$BaselineRunId;amaseBuildRunId=$AmaseBuildRunId;uxasBuildRunId=$UxasBuildRunId;uxasValidationRunId=$UxasValidationRunId;javaHome=$env:JAVA_HOME;cmake=$native.cmake;ninja=$native.ninja;dependenciesPrefix=$dependencies} (Join-Path $run 'context.json')
    & $PythonExecutable -I -B -X utf8 (Join-Path $root 'scripts/g3_protocol/run.py') --root $root --run-id $runId --action $Action.ToLower()
    if($LASTEXITCODE -ne 0) { throw "T02 $Action failed; see $run/result.json" }
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
    if(-not $restored) { $record.status='failed'; $record.error='T02 environment restoration failed.' }
    $record.finishedAt=Get-Date -Format o
    Write-CppJson $record (Join-Path $run 'entry-result.json')
    Write-Host "G3_T02_RUN_ID=$runId"
    if(-not $restored) { throw $record.error }
}
