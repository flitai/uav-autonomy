#requires -Version 5.1
# Integration checks for G1-T01. Run setup-java.ps1 first.
# Fixtures and logs stay under out/. No upstream source is built or modified.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$testRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
. (Join-Path $testRoot 'scripts/windows/java-common.ps1')
$testConfig = Read-JavaToolchain -ProjectRoot $testRoot
$testId = 'g1-t01-validation-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
$testRun = Join-Path $testRoot "out/runs/$testId"
$testTemp = Join-Path $testRoot "out/tmp/$testId"
New-Item -ItemType Directory -Path $testRun,$testTemp -Force | Out-Null
$testResults = [Collections.Generic.List[object]]::new()
$testVariables = @('JAVA_HOME','ANT_HOME','PATH','JAVACMD','CLASSPATH')
$testOriginal = @{}
foreach ($name in $testVariables) { $testOriginal[$name] = [Environment]::GetEnvironmentVariable($name,'Process') }
$testPersistent = foreach ($scope in @('User','Machine')) {
    foreach ($name in $testVariables) {
        [pscustomobject]@{ scope=$scope; name=$name; value=[Environment]::GetEnvironmentVariable($name,$scope) }
    }
}

function Test-Case {
    param([string]$Name, [scriptblock]$Action)
    try {
        & $Action
        $testResults.Add([pscustomobject]@{ name=$Name; status='passed' })
        Write-Host "PASS: $Name"
    } catch {
        $testResults.Add([pscustomobject]@{ name=$Name; status='failed'; error=$_.Exception.Message })
        throw
    }
}

function New-TestProject {
    param([string]$Name)
    $directory = Get-JavaChildPath -Parent $testTemp -Relative $Name
    New-Item -ItemType Directory -Path "$directory/scripts/windows","$directory/config" -Force | Out-Null
    foreach ($file in @('setup-java.ps1','use-java.ps1','java-common.ps1')) {
        Copy-Item -LiteralPath (Join-Path $testRoot "scripts/windows/$file") -Destination "$directory/scripts/windows/$file"
    }
    Copy-Item -LiteralPath (Join-Path $testRoot 'config/windows-java-toolchain.json') -Destination "$directory/config/windows-java-toolchain.json"
    return $directory
}

function Invoke-TestEntry {
    param([string]$Script, [string]$Label, [string]$ExpectedFailure)
    $savedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $lines = @(& "$PSHOME/powershell.exe" -NoProfile -ExecutionPolicy Bypass -File $Script 2>&1)
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $savedPreference }
    $output = ($lines | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
    $output | Set-Content -LiteralPath (Join-Path $testRun "$Label.log") -Encoding UTF8
    Write-Host "$Label exit code: $code"
    if ($ExpectedFailure) {
        if ($code -eq 0 -or $output -notmatch $ExpectedFailure) { throw "Expected failure missing: $Label. See its log." }
    } elseif ($code -ne 0) {
        throw "Unexpected failure: $Label. See its log."
    }
}

function Write-Probe {
    param([string]$Directory)
    New-Item -ItemType Directory -Path "$Directory/src" -Force | Out-Null
    $source = @'
public final class ToolchainProbe {
    public static void main(String[] args) throws Exception {
        System.out.println("PROBE_OK");
        java.nio.file.Files.write(java.nio.file.Paths.get(args[0]),
            System.getProperty("java.home").getBytes(java.nio.charset.StandardCharsets.UTF_8));
    }
}
'@
    $build = @'
<project name="java-toolchain-probe" default="probe" basedir=".">
  <target name="probe">
    <mkdir dir="classes8"/>
    <mkdir dir="classes11"/>
    <javac srcdir="src" destdir="classes8" release="8" includeantruntime="false" encoding="UTF-8"/>
    <javac srcdir="src" destdir="classes11" release="11" includeantruntime="false" encoding="UTF-8"/>
    <java classname="ToolchainProbe" classpath="classes8" fork="false" failonerror="true">
      <arg file="java-home8.txt"/>
    </java>
    <java classname="ToolchainProbe" classpath="classes11" fork="false" failonerror="true">
      <arg file="java-home11.txt"/>
    </java>
  </target>
</project>
'@
    $source | Set-Content -LiteralPath "$Directory/src/ToolchainProbe.java" -Encoding ASCII
    $build | Set-Content -LiteralPath "$Directory/build.xml" -Encoding ASCII
}

function Assert-Probe {
    param([string]$Directory, [string]$ExpectedJavaHome)
    foreach ($target in @(8,11)) {
        $class = [IO.File]::ReadAllBytes("$Directory/classes$target/ToolchainProbe.class")
        $major = $class[6] * 256 + $class[7]
        if ($major -ne ($target + 44)) { throw "Wrong Java $target class version: $major" }
        $actual = Get-Content -LiteralPath "$Directory/java-home$target.txt" -Raw -Encoding UTF8
        if ([IO.Path]::GetFullPath($actual) -ne [IO.Path]::GetFullPath($ExpectedJavaHome)) {
            throw "Ant used an unexpected Java runtime: $actual"
        }
    }
}

Start-Transcript -LiteralPath (Join-Path $testRun 'validation.log') | Out-Null
try {
    Test-Case 'repeat setup from another working directory restores process environment' {
        Push-Location $testTemp
        try { & (Join-Path $testRoot 'scripts/windows/setup-java.ps1') } finally { Pop-Location }
        foreach ($name in $testVariables) {
            if ([Environment]::GetEnvironmentVariable($name,'Process') -cne $testOriginal[$name]) {
                throw "Setup did not restore $name"
            }
        }
        $latest = Get-ChildItem -LiteralPath "$testRoot/out/runs" -Directory -Filter 'g1-t01-setup-*' | Sort-Object Name | Select-Object -Last 1
        $result = Get-Content -LiteralPath "$($latest.FullName)/result.json" -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($result.status -ne 'passed' -or @($result.tools | Where-Object action -ne 'reused').Count) {
            throw 'Repeat setup did not reuse both installed tools.'
        }
    }

    Test-Case 'activation is repeatable and Java 8/11 compile and run under Ant' {
        & (Join-Path $testRoot 'scripts/windows/use-java.ps1')
        $activatedPath = $env:PATH
        & (Join-Path $testRoot 'scripts/windows/use-java.ps1')
        if ($env:PATH -cne $activatedPath) { throw 'Repeated activation duplicated PATH entries.' }
        foreach ($command in @('java.exe','javac.exe')) {
            if ((Get-Command $command).Source -ne (Join-Path $env:JAVA_HOME "bin/$command")) { throw "Unexpected $command" }
        }
        $probe = Join-Path $testTemp 'probe'
        Write-Probe -Directory $probe
        $null = Invoke-JavaToolCheck -File (Join-Path $env:ANT_HOME 'bin/ant.bat') -Arguments @('-nouserlib','-f',"$probe/build.xml")
        Assert-Probe -Directory $probe -ExpectedJavaHome $env:JAVA_HOME
    }

    Test-Case 'missing installation leaves process environment unchanged' {
        $missing = New-TestProject -Name 'missing-tools'
        $before = @{}
        foreach ($name in $testVariables) { $before[$name] = [Environment]::GetEnvironmentVariable($name,'Process') }
        $failed = $false
        try { & "$missing/scripts/windows/use-java.ps1" } catch {
            $failed = $_.Exception.Message -match 'Missing installation receipt'
            $_.Exception.Message | Set-Content -LiteralPath "$testRun/missing-tools.log" -Encoding UTF8
        }
        if (-not $failed) { throw 'Missing tool was not rejected.' }
        foreach ($name in $testVariables) {
            if ([Environment]::GetEnvironmentVariable($name,'Process') -cne $before[$name]) { throw "Failed activation changed $name" }
        }
    }

    Test-Case 'corrupt archive is rejected without installing' {
        $broken = New-TestProject -Name 'corrupt-cache'
        New-Item -ItemType Directory -Path "$broken/.tools/downloads" -Force | Out-Null
        $archive = Join-Path "$broken/.tools/downloads" $testConfig.tools[0].archive
        'deliberately corrupted cache' | Set-Content -LiteralPath $archive -Encoding ASCII
        Invoke-TestEntry -Script "$broken/scripts/windows/setup-java.ps1" -Label 'corrupt-cache' -ExpectedFailure 'Cached archive checksum mismatch'
        if (Test-Path -LiteralPath (Join-Path "$broken/.tools" $testConfig.tools[0].installDirectory)) { throw 'Corrupt archive was installed.' }
    }

    Test-Case 'download failure produces a failed record without a partial installation' {
        $network = New-TestProject -Name 'failed-download'
        $manifest = Get-Content -LiteralPath "$network/config/windows-java-toolchain.json" -Raw -Encoding UTF8 | ConvertFrom-Json
        $manifest.tools[0].url = 'https://127.0.0.1:1/unavailable.zip'
        $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath "$network/config/windows-java-toolchain.json" -Encoding UTF8
        Invoke-TestEntry -Script "$network/scripts/windows/setup-java.ps1" -Label 'failed-download' -ExpectedFailure 'Invoke-WebRequest'
        $record = Get-ChildItem -Path "$network/out/runs/*/result.json" | Select-Object -First 1
        if ((Get-Content -LiteralPath $record.FullName -Raw -Encoding UTF8 | ConvertFrom-Json).status -ne 'failed') { throw 'Failure was not recorded.' }
        if (@(Get-ChildItem -LiteralPath "$network/.tools/downloads" -File).Count) { throw 'Partial download was left behind.' }
    }

    Test-Case 'install and compile under a relocated Unicode and space path' {
        $unicodeName = 'project ' + [char]0x4E2D + [char]0x6587 + ' space'
        $script:relocated = New-TestProject -Name $unicodeName
        New-Item -ItemType Directory -Path "$relocated/.tools/downloads" -Force | Out-Null
        foreach ($tool in $testConfig.tools) {
            Copy-Item -LiteralPath (Join-Path "$testRoot/.tools/downloads" $tool.archive) -Destination "$relocated/.tools/downloads"
        }
        Invoke-TestEntry -Script "$relocated/scripts/windows/setup-java.ps1" -Label 'relocated-setup'
        Write-Probe -Directory "$relocated/probe"
        $runner = @'
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'scripts/windows/use-java.ps1')
& (Join-Path $env:ANT_HOME 'bin/ant.bat') -nouserlib -f (Join-Path $PSScriptRoot 'probe/build.xml')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
'@
        $runner | Set-Content -LiteralPath "$relocated/run-probe.ps1" -Encoding ASCII
        Invoke-TestEntry -Script "$relocated/run-probe.ps1" -Label 'relocated-probe'
        Assert-Probe -Directory "$relocated/probe" -ExpectedJavaHome (Join-Path "$relocated/.tools" $testConfig.tools[0].installDirectory)
    }

    Test-Case 'modified installed file and mismatched receipt are rejected' {
        $ant = $testConfig.tools | Where-Object id -eq 'ant'
        $antDirectory = Join-Path "$relocated/.tools" $ant.installDirectory
        $batch = Join-Path $antDirectory 'bin/ant.bat'
        Add-Content -LiteralPath $batch -Value 'rem deliberately changed test fixture' -Encoding ASCII
        Invoke-TestEntry -Script "$relocated/scripts/windows/use-java.ps1" -Label 'modified-tool' -ExpectedFailure 'Installed file is missing or modified'
        $receiptPath = Join-Path $antDirectory '.uav-toolchain.json'
        $receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $receipt.version = '0.0.0-test'
        $receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
        Invoke-TestEntry -Script "$relocated/scripts/windows/setup-java.ps1" -Label 'mismatched-receipt' -ExpectedFailure 'Installation does not match'
    }

    Test-Case 'real tools, persistent environment and upstream source remain unchanged' {
        foreach ($tool in $testConfig.tools) {
            Assert-JavaToolInstallation -Tool $tool -Directory (Join-Path "$testRoot/.tools" $tool.installDirectory)
        }
        foreach ($item in $testPersistent) {
            if ([Environment]::GetEnvironmentVariable($item.name,$item.scope) -cne $item.value) { throw 'Persistent environment changed.' }
        }
        $changed = @(git -C $testRoot diff --name-only HEAD -- LmcpGen OpenAMASE OpenUxAS)
        if ($LASTEXITCODE -ne 0 -or $changed.Count) { throw 'Upstream source changed.' }
    }
} finally {
    foreach ($name in $testVariables) {
        [Environment]::SetEnvironmentVariable($name,$testOriginal[$name],'Process')
    }
    $testResults | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath "$testRun/results.json" -Encoding UTF8
    Stop-Transcript | Out-Null
    Write-Host "Validation record: $testRun"
}

