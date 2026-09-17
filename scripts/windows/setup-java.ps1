#requires -Version 5.1
<#
.SYNOPSIS
Installs and verifies the locked project-local JDK and Ant, without building the project.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'java-common.ps1')
$projectRoot = Get-JavaProjectRoot
$config = Read-JavaToolchain -ProjectRoot $projectRoot
$toolsRoot = Join-Path $projectRoot '.tools'
$downloadRoot = Join-Path $toolsRoot 'downloads'
$runId = 'g1-t01-setup-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
$runRoot = Join-Path $projectRoot "out/runs/$runId"
New-Item -ItemType Directory -Path $downloadRoot, $runRoot -Force | Out-Null
$environmentBefore = @{}
foreach ($name in @('JAVA_HOME','ANT_HOME','PATH','JAVACMD','CLASSPATH')) {
    $environmentBefore[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$networkBefore = [Net.ServicePointManager]::SecurityProtocol
$progressBefore = $ProgressPreference
$result = [ordered]@{
    started=(Get-Date -Format o); projectRoot=$projectRoot; workingDirectory=(Get-Location).Path
    manifestSHA256=(Get-FileHash -LiteralPath (Join-Path $projectRoot 'config/windows-java-toolchain.json') -Algorithm SHA256).Hash
    status='running'; tools=@(); checks=@()
}
$transcribing = $false
try {
    Start-Transcript -LiteralPath (Join-Path $runRoot 'setup.log') | Out-Null
    $transcribing = $true
    $ProgressPreference = 'SilentlyContinue'
    [Net.ServicePointManager]::SecurityProtocol = $networkBefore -bor [Net.SecurityProtocolType]::Tls12

    # Check existing installations before downloading or installing anything.
    foreach ($tool in $config.tools) {
        $destination = Get-JavaChildPath -Parent $toolsRoot -Relative $tool.installDirectory
        if (Test-Path -LiteralPath $destination) {
            Assert-JavaToolInstallation -Tool $tool -Directory $destination
        }
    }

    foreach ($tool in $config.tools) {
        $destination = Get-JavaChildPath -Parent $toolsRoot -Relative $tool.installDirectory
        $archive = Get-JavaChildPath -Parent $downloadRoot -Relative $tool.archive
        if (Test-Path -LiteralPath $archive) {
            if ((Get-FileHash -LiteralPath $archive -Algorithm $tool.hashAlgorithm).Hash -ne $tool.hash) {
                throw "Cached archive checksum mismatch: $archive. Preserve or remove this file explicitly before retrying."
            }
            Write-Host "Verified cached archive: $($tool.archive)"
        }

        if (Test-Path -LiteralPath $destination) {
            Write-Host "Reusing verified installation: $destination"
            $action = 'reused'
        } else {
            if (-not (Test-Path -LiteralPath $archive)) {
                $partial = Get-JavaChildPath -Parent $downloadRoot -Relative ($tool.archive + '.' + [Guid]::NewGuid().ToString('N') + '.part')
                Write-Host "Downloading locked $($tool.id) $($tool.version)"
                try {
                    Invoke-WebRequest -UseBasicParsing -Uri $tool.url -OutFile $partial -TimeoutSec 600
                    if ((Get-FileHash -LiteralPath $partial -Algorithm $tool.hashAlgorithm).Hash -ne $tool.hash) {
                        throw "Downloaded archive checksum mismatch: $partial"
                    }
                    Move-Item -LiteralPath $partial -Destination $archive
                } finally {
                    if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force }
                }
            }

            $staging = Get-JavaChildPath -Parent $toolsRoot -Relative ('.staging-' + $tool.id + '-' + [Guid]::NewGuid().ToString('N'))
            try {
                Expand-Archive -LiteralPath $archive -DestinationPath $staging
                $roots = @(Get-ChildItem -LiteralPath $staging -Directory)
                if ($roots.Count -ne 1) { throw "Expected one top-level directory in $archive" }
                $extracted = $roots[0].FullName
                $records = foreach ($relative in @($tool.verifyFiles) + @($tool.licenseFiles)) {
                    $file = Get-JavaChildPath -Parent $extracted -Relative $relative
                    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
                        throw "Expected tool file is missing: $relative"
                    }
                    [pscustomobject]@{ path=$relative; sha256=(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash }
                }
                [ordered]@{
                    id=$tool.id; version=$tool.version; hashAlgorithm=$tool.hashAlgorithm
                    archiveHash=$tool.hash; source=$tool.source; files=@($records)
                } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $extracted '.uav-toolchain.json') -Encoding UTF8
                Assert-JavaToolInstallation -Tool $tool -Directory $extracted
                # No overwrite: leave an unexpected destination for the user to inspect.
                if (Test-Path -LiteralPath $destination) { throw "Destination appeared during installation: $destination" }
                $null = Get-JavaChildPath -Parent $staging -Relative $roots[0].Name
                Move-Item -LiteralPath $extracted -Destination $destination
            } finally {
                # Only remove the exact staging directory created by this invocation.
                $checked = Get-JavaChildPath -Parent $toolsRoot -Relative (Split-Path $staging -Leaf)
                if ($checked -ne $staging) { throw 'Staging path validation failed.' }
                if (Test-Path -LiteralPath $checked) { Remove-Item -LiteralPath $checked -Recurse -Force }
            }
            $action = 'installed'
        }
        $result.tools += [pscustomobject]@{ id=$tool.id; version=$tool.version; action=$action; directory=$destination; archiveHash=$tool.hash }
    }

    Set-JavaProcessEnvironment -Config $config -ProjectRoot $projectRoot
    $result.checks += Invoke-JavaToolCheck -File (Join-Path $env:JAVA_HOME 'bin/java.exe') -Arguments @('-version')
    $result.checks += Invoke-JavaToolCheck -File (Join-Path $env:JAVA_HOME 'bin/javac.exe') -Arguments @('-version')
    $result.checks += Invoke-JavaToolCheck -File (Join-Path $env:ANT_HOME 'bin/ant.bat') -Arguments @('-version')
    $jdk = $config.tools | Where-Object { $_.id -eq 'jdk' }
    $ant = $config.tools | Where-Object { $_.id -eq 'ant' }
    $jdkNumber = $jdk.version.Split('+')[0]
    if (-not $result.checks[0].output.Contains($jdk.version) -or
        -not $result.checks[0].output.Contains('64-Bit') -or
        $result.checks[1].output -notmatch ('(?m)^javac ' + [regex]::Escape($jdkNumber) + '\s*$') -or
        -not $result.checks[2].output.Contains("version $($ant.version) ")) {
        throw 'Actual tool versions do not match the manifest.'
    }
    $result.status = 'passed'
    Write-Host 'Locked Java toolchain is ready. No project build was performed.'
} catch {
    $result.status = 'failed'
    $result.error = $_.Exception.Message
    throw
} finally {
    foreach ($name in $environmentBefore.Keys) {
        [Environment]::SetEnvironmentVariable($name, $environmentBefore[$name], 'Process')
    }
    [Net.ServicePointManager]::SecurityProtocol = $networkBefore
    $ProgressPreference = $progressBefore
    $result.finished = Get-Date -Format o
    $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $runRoot 'result.json') -Encoding UTF8
    if ($transcribing) { Stop-Transcript | Out-Null }
    Write-Host "Validation record: $runRoot"
}

