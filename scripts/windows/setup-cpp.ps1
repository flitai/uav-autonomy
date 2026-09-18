#requires -Version 5.1
<# .SYNOPSIS
Prepares the locked Windows C++ tools. Only the Microsoft installer requests elevation.
Use -VerifyOnly to check an existing installation without downloading/installing tools.
Use -PortableOnly to prepare/check CMake, Ninja and vcpkg while system setup is pending.
#>
[CmdletBinding()]
param([switch]$VerifyOnly, [switch]$PortableOnly)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'cpp-common.ps1')
$root = $script:CppProjectRoot
$runId = 'g2-t01-setup-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
$run = Join-Path $root "out/runs/$runId"
New-Item -ItemType Directory -Path $run -Force | Out-Null
$environmentBefore = Get-CppEnvironment
$networkBefore = [Net.ServicePointManager]::SecurityProtocol
$progressBefore = $ProgressPreference
$result = [ordered]@{ started=(Get-Date -Format o); status='running'; workingDirectory=(Get-Location).Path; verifyOnly=[bool]$VerifyOnly; portableOnly=[bool]$PortableOnly; inputs=@(Get-CppInputRecords $root); actions=@() }
$exitCode = 0
try {
    Start-Transcript -LiteralPath (Join-Path $run 'setup.log') | Out-Null
    $config = Read-CppConfig $root
    $result.manifestSHA256 = (Get-FileHash -LiteralPath (Join-Path $root 'config/windows-cpp-toolchain.json')).Hash
    $result.gitHead = (Invoke-CppCommand 'git' @('rev-parse','HEAD') $root $run).output.Trim()
    $result.persistentPathBefore = @{ user=[Environment]::GetEnvironmentVariable('PATH','User'); machine=[Environment]::GetEnvironmentVariable('PATH','Machine') }
    $ProgressPreference = 'SilentlyContinue'
    [Net.ServicePointManager]::SecurityProtocol = $networkBefore -bor [Net.SecurityProtocolType]::Tls12
    # Reject corrupt existing caches even if an extracted tool is already present.
    foreach ($entry in @($config.visualStudio,$config.visualStudio.catalog,$config.vcpkg) + @($config.portable)) {
        $cache = Get-CppChildPath (Join-Path $root '.tools/downloads') $entry.archive
        if (Test-Path -LiteralPath $cache) { Assert-CppHash $cache $entry.sha256 }
    }
    foreach ($tool in $config.portable) {
        $destination = Get-CppChildPath (Join-Path $root '.tools') $tool.directory
        if (Test-Path -LiteralPath $destination) { Assert-CppPortable $tool $destination; $result.actions += "$($tool.id) reused"; continue }
        if ($VerifyOnly) { throw "Missing tool: $($tool.id)" }
        $archive = Get-CppDownload $tool $root
        $stage = Get-CppChildPath (Join-Path $root '.tools') ('.staging-' + [Guid]::NewGuid().ToString('N'))
        Expand-Archive -LiteralPath $archive -DestinationPath $stage
        $extracted = $stage
        if ($tool.archiveRoot) { $extracted = Get-CppChildPath $stage $tool.archiveRoot }
        $files = @(Get-ChildItem -LiteralPath $extracted -Recurse -File | ForEach-Object {
            @{ path=$_.FullName.Substring($extracted.TrimEnd('\').Length+1); sha256=(Get-FileHash -LiteralPath $_.FullName).Hash }
        })
        Write-CppJson @{ id=$tool.id; version=$tool.version; archiveHash=$tool.sha256; files=$files } (Join-Path $extracted '.uav-toolchain.json')
        Assert-CppPortable $tool $extracted
        if (Test-Path -LiteralPath $destination) { throw "Unexpected destination: $destination" }
        Move-Item -LiteralPath $extracted -Destination $destination
        $result.actions += "$($tool.id) installed"
    }
    $vcpkgDir = Get-CppChildPath (Join-Path $root '.tools') $config.vcpkg.directory
    if (-not (Test-Path -LiteralPath $vcpkgDir)) {
        if ($VerifyOnly) { throw 'Missing vcpkg checkout.' }
        $stage = Get-CppChildPath (Join-Path $root '.tools') ('.staging-vcpkg-' + [Guid]::NewGuid().ToString('N'))
        $null = Invoke-CppCommand 'git' @('clone','--no-checkout',$config.vcpkg.repository,$stage) $root $run
        $null = Invoke-CppCommand 'git' @('-C',$stage,'checkout','--detach',$config.vcpkg.commit) $root $run
        $exe = Get-CppDownload $config.vcpkg $root
        Copy-Item -LiteralPath $exe -Destination (Join-Path $stage 'vcpkg.exe')
        if (Test-Path -LiteralPath $vcpkgDir) { throw 'Unexpected vcpkg destination.' }
        Move-Item -LiteralPath $stage -Destination $vcpkgDir
        $result.actions += 'vcpkg installed'
    } else { $result.actions += 'vcpkg reused' }
    if ($PortableOnly) {
        $tools = Set-CppPortableProcessEnvironment $config $root $run
        $result.versions = Test-CppToolVersions $config $tools $root $run
        $result.status = 'portable-ready'
        Write-Host 'Portable tools ready; MSVC/SDK and compile acceptance remain pending.'
    } else {
        $vs = Get-CppVsInstance $config
        if (-not $vs -and $VerifyOnly) { throw 'Locked Build Tools not installed.' }
        $systemReceipt = Join-Path $root '.tools/cpp-system.json'
        if (-not $vs -or (-not $VerifyOnly -and -not (Test-Path -LiteralPath $systemReceipt))) {
            $layout = Initialize-CppVsLayout $config $root $run
            $result.layout = $layout
        }
        if (-not $vs) {
            $bootstrap = Join-Path $layout.directory 'vs_setup.exe'
            $arguments = @('--quiet','--wait','--norestart','--noWeb','--addProductLang','en-US',
                '--channelUri','https://aka.ms/vs/17/release/channel',
                '--installChannelUri',(Join-Path $layout.directory 'ChannelManifest.json'),
                '--installCatalogUri',(Join-Path $layout.directory 'Catalog.json'))
            foreach ($component in $config.visualStudio.components) { $arguments += @('--add',$component) }
            Write-Host 'Starting the Microsoft installer (Windows UAC may request elevation). No automatic reboot.'
            $installer = Invoke-CppBootstrap $bootstrap $arguments (Join-Path $run 'installer') -Elevated
            $result.installer = $installer
            if ($installer.exitCode -in @(3010,1641)) { $result.status='reboot-required'; $exitCode=3010; throw 'Installation requires a Windows reboot; validation has not passed.' }
            if ($installer.exitCode -ne 0) { throw "Microsoft installer failed/cancelled with code $($installer.exitCode)." }
            $vs = Get-CppVsInstance $config
            if (-not $vs) { throw 'Installer returned success without the locked Build Tools instance.' }
            $result.actions += 'Build Tools installed'
        } else { $result.actions += 'Build Tools reused' }
        $system = Get-CppSystemInventory $config $vs
        $systemReceipt = Join-Path $root '.tools/cpp-system.json'
        New-Item -ItemType Directory -Path (Split-Path $systemReceipt) -Force | Out-Null
        if (-not (Test-Path -LiteralPath $systemReceipt)) {
            if ($VerifyOnly) { throw 'Missing system provenance receipt; run setup-cpp.ps1.' }
            # Validate the fixed official catalog before enrolling any installed instance.
            $catalog = Get-CppDownload $config.visualStudio.catalog $root
            $catalogData = Get-Content -LiteralPath $catalog -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($package in $config.visualStudio.packages) {
                if (-not @($catalogData.packages | Where-Object { $_.id -eq $package.id -and $_.version -eq $package.version }).Count) { throw 'Pinned package is absent from the verified Microsoft catalog.' }
            }
            Write-CppJson @{ manifestSHA256=$result.manifestSHA256; catalogSHA256=$config.visualStudio.catalog.sha256; system=$system; layoutProvenance=(Join-Path $run 'layout-provenance.json') } $systemReceipt
        }
        $tools = Set-CppProcessEnvironment $config $root $run
        $result.versions = Test-CppToolVersions $config $tools $root $run
        $result.system = $tools.system
        $result.environment = @{ PATH=$env:PATH; INCLUDE=$env:INCLUDE; LIB=$env:LIB; LIBPATH=$env:LIBPATH; VCToolsVersion=$env:VCToolsVersion; WindowsSDKVersion=$env:WindowsSDKVersion; host=$env:VSCMD_ARG_HOST_ARCH; target=$env:VSCMD_ARG_TGT_ARCH }
        $result.status = 'passed'
        Write-Host 'Tool preparation passed. Compile/run acceptance is a separate test entry.'
    }
} catch {
    if ($result.status -ne 'reboot-required') { $result.status = 'failed'; $exitCode = 1 }
    $result.error = $_.Exception.Message
    Write-Host "FAILED: $($result.error)"
} finally {
    Restore-CppEnvironment $environmentBefore
    [Net.ServicePointManager]::SecurityProtocol = $networkBefore
    $ProgressPreference = $progressBefore
    $result.persistentPathAfter = @{ user=[Environment]::GetEnvironmentVariable('PATH','User'); machine=[Environment]::GetEnvironmentVariable('PATH','Machine') }
    if ($result.persistentPathBefore -and (($result.persistentPathBefore.user -cne $result.persistentPathAfter.user) -or ($result.persistentPathBefore.machine -cne $result.persistentPathAfter.machine))) { $result.status='failed'; $result.error='Persistent PATH changed during preparation; inspect installer effects.'; $exitCode=1 }
    $result.finished = Get-Date -Format o
    Write-CppJson $result (Join-Path $run 'result.json')
    Stop-Transcript -ErrorAction SilentlyContinue | Out-Null
    Write-Host "Validation record: $run"
}
exit $exitCode
