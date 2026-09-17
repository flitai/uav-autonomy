#requires -Version 5.1
<#
.SYNOPSIS
Builds and validates the local LmcpGen with the locked Java toolchain.
.DESCRIPTION
Only publishes a candidate after resource, bytecode and CLI checks pass.
No downloads, message generation, GUI launch or persistent environment changes.
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'java-common.ps1')
$projectRoot = Get-JavaProjectRoot
$runId = 'g1-t02-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
$runDirectory = Get-JavaChildPath -Parent $projectRoot -Relative "out/runs/$runId"
$buildDirectory = Get-JavaChildPath -Parent $projectRoot -Relative "out/build/lmcpgen/$runId"
$candidateDirectory = Join-Path $buildDirectory 'candidate'
$candidateJar = Join-Path $candidateDirectory 'LmcpGen.jar'
$artifactParent = Get-JavaChildPath -Parent $projectRoot -Relative 'out/artifacts'
$artifactDirectory = Get-JavaChildPath -Parent $artifactParent -Relative 'lmcpgen'
$savedLocation = Get-Location
$savedConsoleEncoding = [Console]::OutputEncoding
$environmentNames = @('JAVA_HOME','ANT_HOME','PATH','JAVACMD','CLASSPATH',
    'ANT_ARGS','ANT_OPTS','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS')
$savedEnvironment = @{}
foreach ($name in $environmentNames) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$record = [ordered]@{
    schemaVersion=1; task='G1-T02'; runId=$runId; status='running'; step='preflight'
    startedAt=(Get-Date -Format o); finishedAt=$null; invocationDirectory=$savedLocation.Path
    projectRoot=$projectRoot; buildDirectory=$buildDirectory; runDirectory=$runDirectory
    git=$null; inputs=$null; toolchain=$null; commands=[Collections.Generic.List[object]]::new()
    jarChecks=$null; artifact=$null; error=$null
}
$transcribing = $false
$ownsRunDirectory = $false
$buildLock = $null

function Invoke-LmcpCommand {
    param([string]$Label, [string]$File, [string[]]$Arguments)
    $started = Get-Date -Format o
    $savedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $lines = @(& $File @Arguments 2>&1)
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $savedPreference }
    $output = ($lines | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
    $entry = [pscustomobject]@{ label=$Label; file=$File; arguments=$Arguments
        workingDirectory=(Get-Location).Path; startedAt=$started; finishedAt=(Get-Date -Format o)
        exitCode=$code; output=$output }
    $record.commands.Add($entry)
    $output | Set-Content -LiteralPath (Join-Path $runDirectory "$Label.log") -Encoding UTF8
    Write-Host "[$Label] $File $($Arguments -join ' ')"
    Write-Host $output
    Write-Host "Exit code: $code"
    if ($code -ne 0) { throw "$Label failed with exit code $code." }
    return $entry
}

function Get-LmcpInputs {
    $sourceRoot = Join-Path $projectRoot 'LmcpGen'
    $inputs = foreach ($file in Get-ChildItem -LiteralPath $sourceRoot -Recurse -File | Sort-Object FullName) {
        $relative = $file.FullName.Substring($sourceRoot.Length + 1).Replace('\','/')
        if ($relative -match '^(build|dist)/') { continue }
        [pscustomobject]@{ path="LmcpGen/$relative"; sha256=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash }
    }
    foreach ($relative in @('OpenUxAS/mdms/CMASI.xml','config/windows-java-toolchain.json',
            'scripts/windows/build-lmcpgen.ps1','scripts/windows/use-java.ps1','scripts/windows/java-common.ps1')) {
        $inputs += [pscustomobject]@{path=$relative;sha256=(Get-FileHash -LiteralPath (Join-Path $projectRoot $relative) -Algorithm SHA256).Hash}
    }
    return $inputs
}

function Test-LmcpJar {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($candidateJar)
    try {
        $manifestEntry = $archive.GetEntry('META-INF/MANIFEST.MF')
        if (-not $manifestEntry) { throw 'Missing JAR manifest.' }
        $reader = [IO.StreamReader]::new($manifestEntry.Open())
        try { $manifest = $reader.ReadToEnd() } finally { $reader.Dispose() }
        if ($manifest -notmatch '(?m)^Main-Class: avtas\.lmcp\.lmcpgen\.LmcpGenGUI\r?$') {
            throw 'Unexpected JAR Main-Class.'
        }
        $classes = foreach ($name in @('LmcpGen','LmcpGenGUI','MDMReader')) {
            $entry = $archive.GetEntry("avtas/lmcp/lmcpgen/$name.class")
            if (-not $entry) { throw "Missing compiled class: $name" }
            $stream = $entry.Open()
            $memory = [IO.MemoryStream]::new()
            try { $stream.CopyTo($memory); $bytes = $memory.ToArray() }
            finally { $stream.Dispose(); $memory.Dispose() }
            if ($bytes.Length -lt 8 -or [BitConverter]::ToString($bytes,0,4) -ne 'CA-FE-BA-BE') { throw "Invalid class: $name" }
            $major = [int]$bytes[6] * 256 + [int]$bytes[7]
            if ($major -ne 52) { throw "Expected Java 8 bytecode for $name, got $major." }
            [pscustomobject]@{name=$name;majorVersion=$major}
        }
        $resources = @($record.inputs | Where-Object {
            $_.path -like 'LmcpGen/src/templates/*' -or $_.path -eq 'LmcpGen/src/avtas/lmcp/lmcpgen/MDM.DTD'
        })
        if ($resources.Count -lt 2) { throw 'Missing input DTD or template resources.' }
        foreach ($resource in $resources) {
            $entryName = $resource.path.Substring('LmcpGen/src/'.Length)
            $entry = $archive.GetEntry($entryName)
            if (-not $entry) { throw "Missing packaged resource: $entryName" }
            $stream = $entry.Open()
            $sha = [Security.Cryptography.SHA256]::Create()
            try { $actual = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','') }
            finally { $sha.Dispose(); $stream.Dispose() }
            if ($actual -ne $resource.sha256) { throw "Packaged resource differs from source: $entryName" }
        }
        return [pscustomobject]@{mainClass='avtas.lmcp.lmcpgen.LmcpGenGUI';classes=@($classes)
            resourceCount=$resources.Count;resourceHashesMatch=$true;manifest=$manifest}
    } finally { $archive.Dispose() }
}

try {
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    New-Item -ItemType Directory -Path $runDirectory -ErrorAction Stop | Out-Null
    $ownsRunDirectory = $true
    New-Item -ItemType Directory -Path $buildDirectory -ErrorAction Stop | Out-Null
    Start-Transcript -LiteralPath (Join-Path $runDirectory 'build.log') | Out-Null
    $transcribing = $true
    # Serialize publication. A failed attempt never replaces the last good artifact.
    $lockPath = Get-JavaChildPath -Parent $projectRoot -Relative 'out/build/lmcpgen/build.lock'
    $buildLock = [IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None')
    foreach ($relative in @('LmcpGen/build.xml','LmcpGen/nbproject/build-impl.xml',
            'LmcpGen/nbproject/project.properties','LmcpGen/src/avtas/lmcp/lmcpgen/MDM.DTD','OpenUxAS/mdms/CMASI.xml')) {
        if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $relative) -PathType Leaf)) {
            throw "Required input is missing: $relative"
        }
    }
    Set-Location -LiteralPath $projectRoot
    # Git metadata is unavailable in relocated source fixtures; hashes remain authoritative.
    $gitTop = @(& git -C $projectRoot rev-parse --show-toplevel 2>$null)
    if ($LASTEXITCODE -eq 0 -and $gitTop.Count -eq 1 -and
        [IO.Path]::GetFullPath($gitTop[0]) -eq $projectRoot) {
        $record.git = [ordered]@{head=(& git rev-parse HEAD);lmcpgenTree=(& git rev-parse HEAD:LmcpGen)
            sourceStatus=@(& git status --porcelain -- LmcpGen);baselineKind='local root commit and directory tree; upstream SHA unknown'}
    } else { $record.git = @{head=$null;lmcpgenTree=$null;baselineKind='isolated source copy; see input hashes'} }
    $record.inputs = @(Get-LmcpInputs)
    foreach ($name in @('ANT_ARGS','ANT_OPTS','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS')) {
        [Environment]::SetEnvironmentVariable($name, $null, 'Process')
    }
    & (Join-Path $PSScriptRoot 'use-java.ps1')
    $java = Join-Path $env:JAVA_HOME 'bin/java.exe'
    $javac = Join-Path $env:JAVA_HOME 'bin/javac.exe'
    # Invoke the official Ant launcher with the locked JVM, avoiding user antrc batch hooks.
    $javaDefaults = @('-Dfile.encoding=UTF-8','-Duser.language=en','-Duser.country=US')
    $antPrefix = $javaDefaults + @("-Dant.home=$env:ANT_HOME",'-cp',(Join-Path $env:ANT_HOME 'lib/ant-launcher.jar'),
        'org.apache.tools.ant.launch.Launcher','-nouserlib')
    $record.step = 'tool-check'
    $javaVersion = Invoke-LmcpCommand -Label 'java-version' -File $java -Arguments ($javaDefaults + @('-version'))
    $javacVersion = Invoke-LmcpCommand -Label 'javac-version' -File $javac -Arguments @('-version')
    $antVersion = Invoke-LmcpCommand -Label 'ant-version' -File $java -Arguments ($antPrefix + @('-version'))
    if ($javaVersion.output -notmatch '11\.0\.32\.1\+1' -or $javacVersion.output -notmatch 'javac 11\.0\.32\.1' -or
        $antVersion.output -notmatch 'version 1\.10\.18\b') { throw 'Actual tool versions differ from the G1 baseline.' }
    $record.toolchain = @{javaHome=$env:JAVA_HOME;antHome=$env:ANT_HOME;java=$javaVersion.output;javac=$javacVersion.output;ant=$antVersion.output}
    $record.step = 'ant-build'
    $null = Invoke-LmcpCommand -Label 'ant-build' -File $java -Arguments ($antPrefix + @('-noinput',
        '-f',(Join-Path $projectRoot 'LmcpGen/build.xml'),"-Dbuild.dir=$buildDirectory",
        "-Ddist.dir=$candidateDirectory","-Ddist.jar=$candidateJar",'-Dmkdist.disabled=true',
        '-Djavac.source=1.8','-Djavac.target=1.8','jar'))
    if (-not (Test-Path -LiteralPath $candidateJar -PathType Leaf)) { throw 'Ant produced no candidate JAR.' }
    $record.step = 'jar-validation'
    $record.jarChecks = Test-LmcpJar
    $record.step = 'cli-help'
    $help = Invoke-LmcpCommand -Label 'cli-help' -File $java -Arguments ($javaDefaults + @('-Djava.awt.headless=true','-jar',$candidateJar,'-help'))
    foreach ($token in @('usage: java -jar LmcpGen.jar','-mdm','-mdmdir','-java','-cpp','-py','-dir','-checkMDM')) {
        if (-not $help.output.Contains($token)) { throw "CLI help is missing: $token" }
    }
    $record.step = 'cli-cmasi'
    $mdmPath = Join-Path $projectRoot 'OpenUxAS/mdms/CMASI.xml'
    if (-not (Test-Path -LiteralPath $mdmPath -PathType Leaf)) { throw 'CMASI input disappeared before validation.' }
    $mdm = Invoke-LmcpCommand -Label 'cli-cmasi' -File $java -Arguments ($javaDefaults + @('-Djava.awt.headless=true','-jar',$candidateJar,'-checkMDM',$mdmPath))
    if (-not [string]::IsNullOrWhiteSpace($mdm.output)) { throw 'CMASI validation reported diagnostics, even if the CLI exit code was zero.' }
    $record.step = 'input-stability'
    if ((ConvertTo-Json -InputObject @(Get-LmcpInputs) -Depth 4 -Compress) -cne
        (ConvertTo-Json -InputObject $record.inputs -Depth 4 -Compress)) { throw 'Inputs changed during the build; candidate not published.' }
    $record.artifact = @{path='out/artifacts/lmcpgen/LmcpGen.jar';candidate=$candidateJar
        sha256=(Get-FileHash -LiteralPath $candidateJar -Algorithm SHA256).Hash
        sizeBytes=(Get-Item -LiteralPath $candidateJar).Length;createdAt=(Get-Item -LiteralPath $candidateJar).LastWriteTime.ToString('o')}
    $record.step = 'publish'
    $staging = Get-JavaChildPath -Parent $artifactParent -Relative ".lmcpgen-$runId"
    $backup = Get-JavaChildPath -Parent $buildDirectory -Relative 'previous-artifacts'
    New-Item -ItemType Directory -Path $staging -Force | Out-Null
    Copy-Item -LiteralPath $candidateJar -Destination (Join-Path $staging 'LmcpGen.jar')
    if ((Get-FileHash -LiteralPath (Join-Path $staging 'LmcpGen.jar')).Hash -ne $record.artifact.sha256) { throw 'Staged JAR checksum mismatch.' }
    $record.status = 'passed'
    $record.finishedAt = Get-Date -Format o
    $record | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $staging 'build-info.json') -Encoding UTF8
    $backedUp = $false
    try {
        if (Test-Path -LiteralPath $artifactDirectory) {
            Move-Item -LiteralPath $artifactDirectory -Destination $backup
            $backedUp = $true
        }
        Move-Item -LiteralPath $staging -Destination $artifactDirectory
    } catch {
        if ($backedUp -and -not (Test-Path -LiteralPath $artifactDirectory)) {
            Move-Item -LiteralPath $backup -Destination $artifactDirectory
        }
        throw
    }
    $record.step = 'complete'
    Write-Host "PASS: $artifactDirectory/LmcpGen.jar"
    Write-Host "SHA256: $($record.artifact.sha256)"
} catch {
    $record.status = 'failed'
    $record.error = $_.Exception.Message
    Write-Host "FAIL [$($record.step)]: $($record.error)"
    throw
} finally {
    foreach ($name in $environmentNames) { [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process') }
    [Console]::OutputEncoding = $savedConsoleEncoding
    Set-Location -LiteralPath $savedLocation.Path
    if ($buildLock) { $buildLock.Dispose() }
    $record.finishedAt = Get-Date -Format o
    if ($ownsRunDirectory) {
        $record | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $runDirectory 'result.json') -Encoding UTF8
    }
    if ($transcribing) { Stop-Transcript | Out-Null }
}
