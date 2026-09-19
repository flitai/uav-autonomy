#requires -Version 5.1
<# Read-only G3-T01 qualification. Writes new evidence only; starts no simulation. #>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'uxas-release-common.ps1')
. (Join-Path $PSScriptRoot 'java-common.ps1')
$root = $script:CppProjectRoot
$runId = 'g3-t01-check-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
$run = Join-Path $root ('out/runs/' + $runId)
New-Item -ItemType Directory -Path $run | Out-Null
$before = Get-CppEnvironment
$location = Get-Location
$encoding = [Console]::OutputEncoding
$persistent = @{}
foreach ($scope in @('User','Machine')) { $persistent[$scope] = [Environment]::GetEnvironmentVariable('PATH',$scope) }
$record = [ordered]@{schemaVersion=1;task='G3-T01';runId=$runId;status='running';startedAt=(Get-Date -Format o);invocationDirectory=$location.Path;simulationStarted=$false}
try {
    if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) { throw 'Explicit verified Python executable required.' }
    $PythonExecutable = (Resolve-Path -LiteralPath $PythonExecutable).Path
    [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
    foreach ($name in @('PYTHONPATH','PYTHONHOME','CLASSPATH','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','ANT_ARGS','ANT_OPTS')) {
        [Environment]::SetEnvironmentVariable($name,$null,'Process')
    }
    $qualifiedOutput = @(& { Resolve-UxasPackage -PythonExecutable $PythonExecutable } 6>&1)
    $qualifiedOutput | ForEach-Object { $_.ToString() } | Set-Content -LiteralPath (Join-Path $run 'qualification.log') -Encoding UTF8
    $paths = @($qualifiedOutput | Where-Object { $_ -is [string] })
    if ($paths.Count -ne 1 -or -not (Test-Path -LiteralPath $paths[0] -PathType Container)) { throw 'Resolver did not return exactly one qualified package.' }
    $receiptPaths = @($qualifiedOutput | ForEach-Object { if ($_.ToString() -match 'T07 evidence: (.+)$') { $Matches[1] } })
    if ($receiptPaths.Count -ne 1) { throw 'Missing unique qualification receipt.' }
    $resolveRunId = Split-Path -Leaf $receiptPaths[0]
    $javaConfig = Read-JavaToolchain -ProjectRoot $root
    Set-JavaProcessEnvironment -Config $javaConfig -ProjectRoot $root
    $java = Join-Path $env:JAVA_HOME 'bin/java.exe'
    $versions = @(
        (Invoke-JavaToolCheck -File $java -Arguments @('-version')),
        (Invoke-JavaToolCheck -File (Join-Path $env:JAVA_HOME 'bin/javac.exe') -Arguments @('-version')),
        (Invoke-JavaToolCheck -File $java -Arguments @('-Dfile.encoding=UTF-8',('-Dant.home='+$env:ANT_HOME),'-cp',(Join-Path $env:ANT_HOME 'lib/ant-launcher.jar'),'org.apache.tools.ant.launch.Launcher','-version'))
    )
    Write-CppJson @{javaTools=$versions;javaHome=$env:JAVA_HOME;antHome=$env:ANT_HOME;qualifiedPackage=$paths[0];resolveRunId=$resolveRunId} (Join-Path $run 'context.json')
    & $PythonExecutable -I -B -X utf8 (Join-Path $root 'scripts/g3_baseline/check.py') --root $root --run-id $runId
    if ($LASTEXITCODE -ne 0) { throw "G3 baseline failed; see $run/result.json" }
    $record.status = 'passed'
} catch {
    $record.status = 'failed'; $record.error = $_.Exception.Message
    throw
} finally {
    Restore-CppEnvironment $before
    Set-Location -LiteralPath $location.Path
    [Console]::OutputEncoding = $encoding
    $after = Get-CppEnvironment
    $record.environmentRestored = (@(Compare-Object @($before.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) @($after.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" })).Count -eq 0)
    $record.locationRestored = ((Get-Location).Path -ceq $location.Path)
    $record.encodingRestored = ([Console]::OutputEncoding.CodePage -eq $encoding.CodePage)
    $record.persistentPathUnchanged = $true
    foreach ($scope in @('User','Machine')) { if ($persistent[$scope] -cne [Environment]::GetEnvironmentVariable('PATH',$scope)) { $record.persistentPathUnchanged = $false } }
    $restored = $record.environmentRestored -and $record.locationRestored -and $record.encodingRestored -and $record.persistentPathUnchanged
    if (-not $restored) { $record.status='failed'; $record.error='G3 entry restoration failed.' }
    $record.finishedAt = Get-Date -Format o
    Write-CppJson $record (Join-Path $run 'entry-result.json')
    Write-Host "G3_T01_RUN_ID=$runId"
    if (-not $restored) { throw $record.error }
}
