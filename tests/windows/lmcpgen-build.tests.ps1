#requires -Version 5.1
# G1-T02 integration checks. Faults are confined to an isolated source/tool copy.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$testRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
. (Join-Path $testRoot 'scripts/windows/java-common.ps1')
$testId = 'g1-t02-validation-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
$testRun = Get-JavaChildPath -Parent $testRoot -Relative "out/runs/$testId"
$testTemp = Get-JavaChildPath -Parent $testRoot -Relative "out/tmp/$testId"
New-Item -ItemType Directory -Path $testRun,$testTemp | Out-Null
$results = [Collections.Generic.List[object]]::new()
$originalLocation = Get-Location
$initialHead = & git -C $testRoot rev-parse HEAD
$variableNames = @('JAVA_HOME','ANT_HOME','PATH','JAVACMD','CLASSPATH',
    'ANT_ARGS','ANT_OPTS','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS')
$persistentBefore = foreach ($scope in @('User','Machine')) {
    foreach ($name in $variableNames) { "$scope|$name|$([Environment]::GetEnvironmentVariable($name,$scope))" }
}
$policyBefore = Get-ExecutionPolicy -List | ConvertTo-Json -Compress

function Test-Case {
    param([string]$Name,[scriptblock]$Action)
    try {
        & $Action
        $results.Add([pscustomobject]@{name=$Name;status='passed'})
        Write-Host "PASS: $Name"
    } catch {
        $results.Add([pscustomobject]@{name=$Name;status='failed';error=$_.Exception.Message})
        throw
    }
}

function Read-BuildInfo {
    param([string]$Root)
    Get-Content -LiteralPath (Join-Path $Root 'out/artifacts/lmcpgen/build-info.json') -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Invoke-Entry {
    param([string]$Root,[string]$Label,[string]$ExpectedError,[string]$Script,[string[]]$Arguments=@())
    if (-not $Script) { $Script = Join-Path $Root 'scripts/windows/build-lmcpgen.ps1' }
    $preference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $lines = @(& "$PSHOME/powershell.exe" -NoProfile -ExecutionPolicy Bypass -File $Script @Arguments 2>&1)
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $preference }
    $output = ($lines | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
    $output | Set-Content -LiteralPath (Join-Path $testRun "$Label.log") -Encoding UTF8
    $latest = Get-ChildItem -LiteralPath (Join-Path $Root 'out/runs') -Directory |
        Where-Object { $_.Name -match '^g1-t02-\d{8}-\d{6}-\d{3}$' } | Sort-Object Name | Select-Object -Last 1
    $record = Get-Content -LiteralPath (Join-Path $latest.FullName 'result.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    [pscustomobject]@{exitCode=$code;record=$record;workingDirectory=(Get-Location).Path;script=$Script;arguments=$Arguments} |
        ConvertTo-Json -Depth 14 | Set-Content -LiteralPath (Join-Path $testRun "$Label.json") -Encoding UTF8
    if ($ExpectedError) {
        if ($code -ne 1 -or $record.status -ne 'failed' -or $record.error -notmatch $ExpectedError) { throw "Expected failure missing: $Label" }
    } elseif ($code -ne 0 -or $record.status -ne 'passed') { throw "Unexpected build failure: $Label. See the log." }
    return $record
}

function Assert-GoodArtifactUnchanged {
    foreach ($item in $goodArtifactHashes) {
        if ((Get-FileHash -LiteralPath $item.Path).Hash -ne $item.Hash) { throw 'A failed attempt changed the previous good artifact or its provenance.' }
    }
}

try {
    Start-Transcript -LiteralPath (Join-Path $testRun 'validation.log') | Out-Null
    Test-Case 'Fresh repeat build from another working directory; process environment restored' {
        $previous = Read-BuildInfo -Root $testRoot
        $probe = Join-Path $testTemp 'environment-probe.ps1'
        @'
param([string]$ProjectRoot)
$ErrorActionPreference = 'Stop'
$names = @('JAVA_HOME','ANT_HOME','PATH','JAVACMD','CLASSPATH','ANT_ARGS','ANT_OPTS','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS')
foreach ($name in @('ANT_ARGS','ANT_OPTS','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS')) {
    [Environment]::SetEnvironmentVariable($name,'deliberately-invalid-test-value','Process')
}
$before = @{}
foreach ($name in $names) { $before[$name] = [Environment]::GetEnvironmentVariable($name,'Process') }
$cwd = (Get-Location).Path
$encoding = [Console]::OutputEncoding.CodePage
& (Join-Path $ProjectRoot 'scripts/windows/build-lmcpgen.ps1')
foreach ($name in $names) {
    if ([Environment]::GetEnvironmentVariable($name,'Process') -cne $before[$name]) { throw "Environment not restored: $name" }
}
if ((Get-Location).Path -ne $cwd -or [Console]::OutputEncoding.CodePage -ne $encoding) { throw 'Location or encoding not restored.' }
Write-Host 'PROCESS_RESTORATION_OK'
# Force an existing run identifier; failure must not overwrite another run's result.
$completed = Get-Content -LiteralPath (Join-Path $ProjectRoot 'out/artifacts/lmcpgen/build-info.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$recordPath = Join-Path $completed.runDirectory 'result.json'
$recordHash = (Get-FileHash -LiteralPath $recordPath).Hash
function Get-Date {
    param([string]$Format)
    if ($Format -eq 'yyyyMMdd-HHmmss-fff') { return $completed.runId.Substring('g1-t02-'.Length) }
    Microsoft.PowerShell.Utility\Get-Date -Format $Format
}
$rejected = $false
try { & (Join-Path $ProjectRoot 'scripts/windows/build-lmcpgen.ps1') }
catch { $rejected = $true }
if (-not $rejected -or (Get-FileHash -LiteralPath $recordPath).Hash -ne $recordHash) { throw 'Run collision overwrote existing evidence.' }
foreach ($name in $names) {
    if ([Environment]::GetEnvironmentVariable($name,'Process') -cne $before[$name]) { throw "Failure path did not restore: $name" }
}
if ((Get-Location).Path -ne $cwd -or [Console]::OutputEncoding.CodePage -ne $encoding) { throw 'Failure path did not restore location or encoding.' }
Write-Host 'RUN_COLLISION_REJECTED'
'@ | Set-Content -LiteralPath $probe -Encoding ASCII
        Set-Location -LiteralPath $testTemp
        $current = Invoke-Entry -Root $testRoot -Label 'repeat-and-environment' -Script $probe -Arguments @('-ProjectRoot',$testRoot)
        if ($current.runId -eq $previous.runId -or $current.buildDirectory -eq $previous.buildDirectory) { throw 'Build reused old output.' }
        if ($current.jarChecks.resourceCount -ne $previous.jarChecks.resourceCount) { throw 'Resource count changed on repeat build.' }
    }
    $formal = Read-BuildInfo -Root $testRoot
    $formalHash = (Get-FileHash -LiteralPath (Join-Path $testRoot 'out/artifacts/lmcpgen/LmcpGen.jar')).Hash
    # Encode the Unicode name explicitly to keep this PowerShell 5.1 source ASCII-safe.
    $fixtureName = 'project ' + [char]0x4e2d + [char]0x6587 + ' space'
    $fixture = Get-JavaChildPath -Parent $testTemp -Relative $fixtureName
    Test-Case 'Actual source build and CLI in a Chinese and spaced project path' {
        New-Item -ItemType Directory -Path "$fixture/scripts/windows","$fixture/config","$fixture/OpenUxAS/mdms","$fixture/.tools","$fixture/LmcpGen" -Force | Out-Null
        foreach ($name in @('build-lmcpgen.ps1','java-common.ps1','use-java.ps1')) {
            Copy-Item -LiteralPath (Join-Path $testRoot "scripts/windows/$name") -Destination "$fixture/scripts/windows/$name"
        }
        Copy-Item -LiteralPath (Join-Path $testRoot 'config/windows-java-toolchain.json') -Destination "$fixture/config"
        Copy-Item -LiteralPath (Join-Path $testRoot 'OpenUxAS/mdms/CMASI.xml') -Destination "$fixture/OpenUxAS/mdms"
        foreach ($item in Get-ChildItem -LiteralPath (Join-Path $testRoot 'LmcpGen') -Force) {
            if ($item.Name -notin @('build','dist','.git')) { Copy-Item -LiteralPath $item.FullName -Destination "$fixture/LmcpGen" -Recurse }
        }
        $config = Read-JavaToolchain -ProjectRoot $testRoot
        foreach ($tool in $config.tools) {
            Copy-Item -LiteralPath (Join-Path $testRoot ".tools/$($tool.installDirectory)") -Destination "$fixture/.tools" -Recurse
        }
        $copyRecord = Invoke-Entry -Root $fixture -Label 'unicode-build'
        if ($copyRecord.jarChecks.resourceCount -ne $formal.jarChecks.resourceCount) { throw 'Relocated build lost resources.' }
        if ($copyRecord.git.head) { throw 'Isolated copy incorrectly claims parent Git metadata.' }
    }
    $goodArtifactHashes = @('LmcpGen.jar','build-info.json') | ForEach-Object {
        Get-FileHash -LiteralPath (Join-Path $fixture "out/artifacts/lmcpgen/$_")
    }
    $model = Get-JavaChildPath -Parent $fixture -Relative 'OpenUxAS/mdms/CMASI.xml'
    $savedModel = Get-JavaChildPath -Parent $fixture -Relative 'OpenUxAS/mdms/CMASI.saved'
    Test-Case 'Missing model rejected before invoking Java; previous artifact preserved' {
        Move-Item -LiteralPath $model -Destination $savedModel
        try {
            $failed = Invoke-Entry -Root $fixture -Label 'missing-model' -ExpectedError 'Required input is missing'
            if ($failed.commands.Count -ne 0 -or $failed.step -ne 'preflight') { throw 'Missing model was not rejected at preflight.' }
            Assert-GoodArtifactUnchanged
        } finally { Move-Item -LiteralPath $savedModel -Destination $model }
    }
    Test-Case 'Malformed model rejected despite legacy CLI exit zero; previous artifact preserved' {
        $bytes = [IO.File]::ReadAllBytes($model)
        try {
            [IO.File]::WriteAllText($model,'<MDM>',[Text.UTF8Encoding]::new($false))
            $failed = Invoke-Entry -Root $fixture -Label 'malformed-model' -ExpectedError 'CMASI validation reported diagnostics'
            $command = @($failed.commands | Where-Object label -eq 'cli-cmasi')
            if ($command.Count -ne 1 -or $command[0].exitCode -ne 0 -or [string]::IsNullOrWhiteSpace($command[0].output)) { throw 'Legacy zero-exit diagnostic not reproduced.' }
            Assert-GoodArtifactUnchanged
        } finally { [IO.File]::WriteAllBytes($model,$bytes) }
    }
    Test-Case 'Compiler error rejected without publishing or running CLI' {
        $broken = Get-JavaChildPath -Parent $fixture -Relative 'LmcpGen/src/avtas/lmcp/lmcpgen/G1Broken.java'
        try {
            [IO.File]::WriteAllText($broken,'public class G1Broken { syntax error }',[Text.UTF8Encoding]::new($false))
            $failed = Invoke-Entry -Root $fixture -Label 'compile-error' -ExpectedError 'ant-build failed with exit code'
            if ($failed.step -ne 'ant-build' -or @($failed.commands | Where-Object label -like 'cli-*').Count) { throw 'Compile error did not stop validation.' }
            Assert-GoodArtifactUnchanged
        } finally {
            # Single fixture file; its resolved path was constrained to the isolated project above.
            if (Test-Path -LiteralPath $broken) { Remove-Item -LiteralPath $broken }
        }
    }
    Test-Case 'Formal tools, source, output boundaries and persistent configuration unchanged' {
        $config = Read-JavaToolchain -ProjectRoot $testRoot
        foreach ($tool in $config.tools) { Assert-JavaToolInstallation -Tool $tool -Directory (Join-Path $testRoot ".tools/$($tool.installDirectory)") }
        if ((Get-FileHash -LiteralPath (Join-Path $testRoot 'out/artifacts/lmcpgen/LmcpGen.jar')).Hash -ne $formalHash) { throw 'Fault tests changed the formal artifact.' }
        foreach ($relative in @('LmcpGen/build','LmcpGen/dist','OpenAMASE/OpenAMASE/build','OpenAMASE/OpenAMASE/dist','out/generated')) {
            if (Test-Path -LiteralPath (Join-Path $testRoot $relative)) { throw "Unexpected output: $relative" }
        }
        if (@(& git -C $testRoot diff --name-only HEAD -- LmcpGen OpenAMASE OpenUxAS).Count -ne 0) { throw 'Upstream tracked source changed.' }
        if ((& git -C $testRoot rev-parse HEAD) -ne $initialHead) { throw 'Git HEAD changed.' }
        foreach ($scope in @('User','Machine')) {
            foreach ($name in $variableNames) {
                if ("$scope|$name|$([Environment]::GetEnvironmentVariable($name,$scope))" -cnotin $persistentBefore) { throw "Persistent environment changed: $scope/$name" }
            }
        }
        if ((Get-ExecutionPolicy -List | ConvertTo-Json -Compress) -cne $policyBefore) { throw 'Execution policy changed.' }
        foreach ($path in @('out/build/lmcpgen/probe','out/artifacts/lmcpgen/LmcpGen.jar','out/runs/probe')) {
            $null = & git -C $testRoot check-ignore -- $path
            if ($LASTEXITCODE -ne 0) { throw "Output not ignored: $path" }
        }
    }
} finally {
    Set-Location -LiteralPath $originalLocation.Path
    $results | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $testRun 'results.json') -Encoding UTF8
    Stop-Transcript | Out-Null
    Write-Host "Validation records: $testRun"
}
