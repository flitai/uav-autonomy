#requires -Version 5.1
# Helpers for the project-owned C++ toolchain. No persistent environment changes.
$script:CppProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))

function Get-CppChildPath {
    param([string]$Parent, [string]$Relative)
    $base = [IO.Path]::GetFullPath($Parent).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
    $path = [IO.Path]::GetFullPath((Join-Path $base $Relative))
    if (-not $path.StartsWith($base, [StringComparison]::OrdinalIgnoreCase)) { throw "Path escapes owned directory: $Relative" }
    return $path
}

function Write-CppJson {
    param($Value, [string]$Path)
    $Value | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Get-CppInputRecords {
    param([string]$Root)
    $paths = @('config/windows-cpp-toolchain.json','scripts/windows/cpp-common.ps1','scripts/windows/setup-cpp.ps1','scripts/windows/use-cpp.ps1','tests/windows/cpp-toolchain.tests.ps1','tests/cpp_toolchain/CMakeLists.txt','tests/cpp_toolchain/c_probe.c','tests/cpp_toolchain/cpp_probe.cpp')
    foreach ($relative in $paths) {
        $file = Join-Path $Root $relative
        if (Test-Path -LiteralPath $file -PathType Leaf) { @{ path=$relative; sha256=(Get-FileHash -LiteralPath $file).Hash } }
    }
}

function Read-CppConfig {
    param([string]$Root = $script:CppProjectRoot)
    $config = Get-Content -LiteralPath (Join-Path $Root 'config/windows-cpp-toolchain.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($config.schemaVersion -ne 1 -or $config.platform -ne 'windows-x64' -or -not [Environment]::Is64BitProcess) {
        throw 'The C++ manifest requires schema 1 and 64-bit Windows PowerShell.'
    }
    foreach ($entry in @($config.visualStudio, $config.visualStudio.catalog, $config.vcpkg) + @($config.portable)) {
        if ($entry.sha256 -notmatch '^[a-fA-F0-9]{64}$' -or $entry.url -notlike 'https://*') { throw 'Invalid pinned download.' }
    }
    return $config
}

function Assert-CppHash {
    param([string]$Path, [string]$Hash)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Required file missing: $Path" }
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ne $Hash) { throw "Checksum mismatch: $Path" }
}

function Get-CppDownload {
    param($Entry, [string]$Root)
    $cache = Join-Path $Root '.tools/downloads'
    New-Item -ItemType Directory -Path $cache -Force | Out-Null
    $file = Get-CppChildPath $cache $Entry.archive
    if (Test-Path -LiteralPath $file) { Assert-CppHash $file $Entry.sha256; return $file }
    $partial = $file + '.' + [Guid]::NewGuid().ToString('N') + '.part'
    Write-Host "Downloading $($Entry.archive)"
    # Preserve incomplete/invalid downloads for diagnosis; never overwrite a verified cache.
    Invoke-WebRequest -UseBasicParsing -Uri $Entry.url -OutFile $partial -TimeoutSec 900
    Assert-CppHash $partial $Entry.sha256
    Move-Item -LiteralPath $partial -Destination $file
    return $file
}

function Invoke-CppCommand {
    param([string]$File, [string[]]$Arguments = @(), [string]$Directory, [string]$LogRoot, [switch]$AllowFailure)
    $before = $ErrorActionPreference
    Push-Location -LiteralPath $Directory
    try {
        $ErrorActionPreference = 'Continue'
        $global:LASTEXITCODE = $null
        $lines = @(& $File @Arguments 2>&1 | ForEach-Object { "$_" })
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $before; Pop-Location }
    $record = [ordered]@{ file=$File; arguments=$Arguments; workingDirectory=$Directory; exitCode=$code; output=($lines -join "`n") }
    if ($LogRoot) { Write-CppJson $record (Join-Path $LogRoot ('command-' + [Guid]::NewGuid().ToString('N') + '.json')) }
    if ($null -eq $code -or ($code -ne 0 -and -not $AllowFailure)) { throw "Command failed ($code): $File`n$($record.output)" }
    return [pscustomobject]$record
}

function Get-CppEnvironment {
    $snapshot = @{}
    foreach ($item in [Environment]::GetEnvironmentVariables('Process').GetEnumerator()) { $snapshot[$item.Key] = $item.Value }
    return $snapshot
}

function Restore-CppEnvironment {
    param([hashtable]$Snapshot)
    foreach ($key in @([Environment]::GetEnvironmentVariables('Process').Keys)) {
        if (-not $Snapshot.ContainsKey($key)) { [Environment]::SetEnvironmentVariable($key, $null, 'Process') }
    }
    $current = [Environment]::GetEnvironmentVariables('Process')
    foreach ($key in $Snapshot.Keys) {
        if ($current.Contains($key) -and $current[$key] -ceq $Snapshot[$key]) { continue }
        if ($Snapshot[$key] -ceq '') {
            # .NET Framework deletes empty values; Win32 distinguishes empty from absent.
            if (-not ('UavCpp.NativeEnvironment' -as [type])) {
                Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
namespace UavCpp {
    public static class NativeEnvironment {
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool SetEnvironmentVariable(string name, string value);
    }
}
'@
            }
            if (-not [UavCpp.NativeEnvironment]::SetEnvironmentVariable($key,'')) { throw "Cannot restore empty environment variable: $key" }
        } else { [Environment]::SetEnvironmentVariable($key, $Snapshot[$key], 'Process') }
    }
}

function Invoke-CppBootstrap {
    param([string]$Bootstrap, [string[]]$Arguments, [string]$LogRoot, [switch]$Elevated)
    $started=Get-Date
    $record=[ordered]@{ started=$started.ToString('o'); file=$Bootstrap; arguments=$Arguments; elevated=[bool]$Elevated; status='running' }
    New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
    $request=Join-Path $LogRoot 'result.json'
    Write-CppJson $record $request
    try {
        $quoted=@($Arguments | ForEach-Object {
            if ($_ -match '"') { throw 'Embedded quotes are not allowed in installer arguments.' }
            '"' + ($_ -replace '(\\+)$','$1$1') + '"'
        })
        $start=@{ FilePath=$Bootstrap; ArgumentList=$quoted; WindowStyle='Hidden'; PassThru=$true }
        if ($Elevated) { $start.Verb='RunAs' }
        $process=Start-Process @start
        $record.pid=$process.Id
        Write-CppJson $record $request
        while (-not $process.WaitForExit(1000)) { }
        $process.Refresh()
        $record.exitCode=$process.ExitCode
        $record.status='finished'
    } catch { $record.status='failed'; $record.error=$_.Exception.Message; throw }
    finally {
        $record.finished=Get-Date -Format o
        $logs=@()
        Get-ChildItem -LiteralPath $env:TEMP -Filter 'dd_*' -File | Where-Object { $_.LastWriteTime -ge $started } | ForEach-Object {
            $destination=Join-Path $LogRoot $_.Name
            Copy-Item -LiteralPath $_.FullName -Destination $destination
            $logs+=@{path=$destination;sha256=(Get-FileHash -LiteralPath $destination).Hash}
        }
        $record.logs=$logs
        Write-CppJson $record $request
    }
    return [pscustomobject]$record
}

function Initialize-CppVsLayout {
    param($Config, [string]$Root, [string]$LogRoot)
    $bootstrap=Get-CppDownload $Config.visualStudio $Root
    $signature=Get-AuthenticodeSignature -LiteralPath $bootstrap
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') { throw 'Invalid Microsoft bootstrapper signature.' }
    # The entity hash was enrolled only after Microsoft ManifestVerifier succeeded and
    # a tampered catalog failed InvalidSignature. Retain the differing channel metadata.
    $downloaded=Get-CppDownload $Config.visualStudio.catalog $Root
    $layout=Get-CppChildPath (Join-Path $Root '.tools') $Config.visualStudio.layoutDirectory
    $catalog=Join-Path $layout 'Catalog.json'
    if (Test-Path -LiteralPath $catalog) { Assert-CppHash $catalog $Config.visualStudio.catalog.sha256 }
    $arguments=@('--layout',$layout,'--lang','en-US','--wait','--quiet','--norestart')
    if (Test-Path -LiteralPath $catalog) { $arguments+='--keepLayoutVersion' }
    foreach ($component in $Config.visualStudio.components) { $arguments+=@('--add',$component) }
    Write-Host 'Preparing the fixed Microsoft layout and validating its signed manifest.'
    $prepared=Invoke-CppBootstrap $bootstrap $arguments (Join-Path $LogRoot 'layout-prepare')
    if ($prepared.exitCode -ne 0) { throw "Microsoft layout preparation failed: $($prepared.exitCode)" }
    Assert-CppHash $catalog $Config.visualStudio.catalog.sha256
    Assert-CppHash (Join-Path $layout 'vs_setup.exe') $Config.visualStudio.sha256
    Assert-CppHash (Join-Path $layout 'vs_installer.opc') $Config.visualStudio.installerPackageSHA256
    $data=Get-Content -LiteralPath $catalog -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($data.info.buildVersion -ne $Config.visualStudio.buildVersion) { throw 'Layout selected an unexpected product version.' }
    foreach ($package in $Config.visualStudio.packages) {
        if (-not @($data.packages | Where-Object { $_.id -eq $package.id -and $_.version -eq $package.version }).Count) { throw "Pinned package is absent from the signed catalog: $($package.id)" }
    }
    $verified=Invoke-CppBootstrap $bootstrap @('--layout',$layout,'--verify','--wait','--quiet','--norestart') (Join-Path $LogRoot 'layout-verify')
    $logText=(Get-ChildItem -LiteralPath (Join-Path $LogRoot 'layout-verify') -Filter 'dd_setup*.log' -File | ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw }) -join "`n"
    if ($verified.exitCode -ne 0 -or $logText -notmatch 'ManifestVerifier Result: Success' -or $logText -match 'ManifestVerifier Result: InvalidSignature') { throw 'Microsoft native layout/manifest verification did not pass.' }
    $records=@(foreach ($name in @('Catalog.json','ChannelManifest.json','Response.json','vs_setup.exe','vs_installer.opc','vs_installer.version.json')) {
        @{path=$name;sha256=(Get-FileHash -LiteralPath (Join-Path $layout $name)).Hash}
    })
    $receipt=@{ directory=$layout; bootstrapperSigner=$signature.SignerCertificate.Subject; catalogSHA256=$Config.visualStudio.catalog.sha256; channelDeclaredSHA256=$Config.visualStudio.catalog.channelDeclaredSHA256; nativeVerification=$verified; files=$records }
    Write-CppJson $receipt (Join-Path $LogRoot 'layout-provenance.json')
    return [pscustomobject]$receipt
}

function Get-CppVsInstance {
    param($Config)
    $where = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
    if (-not (Test-Path -LiteralPath $where)) { return $null }
    $query = Invoke-CppCommand $where @('-all','-products','Microsoft.VisualStudio.Product.BuildTools','-format','json','-utf8') $script:CppProjectRoot
    $instances = @($query.output | ConvertFrom-Json)
    if ($instances.Count -eq 0) { return $null }
    $matched = @($instances | Where-Object { $_.installationVersion -eq $Config.visualStudio.buildVersion })
    if ($matched.Count -ne 1) { throw 'Existing Build Tools instance does not uniquely match the lock; no automatic upgrade/downgrade.' }
    $instance = $matched[0]
    if (-not $instance.isComplete -or -not $instance.isLaunchable -or $instance.isRebootRequired) {
        throw 'Build Tools installation is incomplete or requires a reboot. Resume after completing the Windows installation.'
    }
    return $instance
}

function Get-CppSystemInventory {
    param($Config, $Instance)
    $statePath = Join-Path $env:ProgramData "Microsoft/VisualStudio/Packages/_Instances/$($Instance.instanceId)/state.json"
    $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $packagesPath = Join-Path (Split-Path $statePath) 'state.packages.json'
    $packages = (Get-Content -LiteralPath $packagesPath -Raw -Encoding UTF8 | ConvertFrom-Json).packages
    foreach ($expected in $Config.visualStudio.packages) {
        if (-not @($packages | Where-Object { $_.id -eq $expected.id -and $_.version -eq $expected.version }).Count) {
            throw "Installed package differs from pinned catalog: $($expected.id) $($expected.version)"
        }
    }
    foreach ($component in $Config.visualStudio.components) {
        if (-not @($packages | Where-Object { $_.id -eq $component }).Count) { throw "Required component missing: $component" }
    }
    $defaultFile = Join-Path $Instance.installationPath 'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt'
    $vcVersion = (Get-Content -LiteralPath $defaultFile -Raw).Trim()
    $vc = Join-Path $Instance.installationPath "VC/Tools/MSVC/$vcVersion"
    $sdk = (Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows Kits\Installed Roots' -ErrorAction SilentlyContinue).KitsRoot10
    if (-not $sdk) { $sdk = (Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows Kits\Installed Roots').KitsRoot10 }
    $kit = $Config.visualStudio.sdkKitVersion
    $files = @($defaultFile, $statePath, $packagesPath)
    foreach ($relative in @('bin/Hostx64/x64/cl.exe','bin/Hostx64/x64/link.exe','bin/Hostx64/x64/c1.dll','bin/Hostx64/x64/c1xx.dll','bin/Hostx64/x64/c2.dll','bin/Hostx64/x64/dumpbin.exe','include/vcruntime.h','lib/x64/msvcrt.lib','lib/x64/vcruntime.lib','lib/x64/msvcprt.lib')) { $files += Join-Path $vc $relative }
    foreach ($relative in @("Include/$kit/um/Windows.h","Include/$kit/ucrt/stdio.h","Lib/$kit/um/x64/kernel32.lib","Lib/$kit/ucrt/x64/ucrt.lib","bin/$kit/x64/rc.exe")) { $files += Join-Path $sdk $relative }
    $records = foreach ($file in $files) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Required SDK/MSVC file missing: $file" }
        [ordered]@{ path=$file; sha256=(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash; version=(Get-Item -LiteralPath $file).VersionInfo.FileVersion }
    }
    $installedPackages=@($packages | Where-Object { $_.id -in $Config.visualStudio.packages.id -or $_.id -eq 'Microsoft.VisualCpp.Redist.14.Latest' } | Select-Object id,version,chip)
    return [pscustomobject]@{ instance=$Instance; vcVersion=$vcVersion; vcDirectory=$vc; sdkDirectory=$sdk; sdkKitVersion=$kit; packages=$installedPackages; files=@($records) }
}

function Assert-CppPortable {
    param($Tool, [string]$Directory)
    $receipt = Get-Content -LiteralPath (Join-Path $Directory '.uav-toolchain.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($receipt.id -ne $Tool.id -or $receipt.version -ne $Tool.version -or $receipt.archiveHash -ne $Tool.sha256) { throw "Tool receipt version mismatch: $Directory" }
    if (-not $receipt.files.Count) { throw "Empty tool receipt: $Directory" }
    foreach ($file in $receipt.files) { Assert-CppHash (Get-CppChildPath $Directory $file.path) $file.sha256 }
    if (-not (Test-Path -LiteralPath (Get-CppChildPath $Directory $Tool.executable))) { throw "Tool executable missing: $Directory" }
}

function Assert-CppVcpkg {
    param($Config, [string]$Root, [string]$LogRoot)
    $directory = Get-CppChildPath (Join-Path $Root '.tools') $Config.vcpkg.directory
    Assert-CppHash (Join-Path $directory 'vcpkg.exe') $Config.vcpkg.sha256
    $head = Invoke-CppCommand 'git' @('-C',$directory,'rev-parse','HEAD') $Root $LogRoot
    $dirty = Invoke-CppCommand 'git' @('-C',$directory,'status','--porcelain','--untracked-files=no') $Root $LogRoot
    $shallow = Invoke-CppCommand 'git' @('-C',$directory,'rev-parse','--is-shallow-repository') $Root $LogRoot
    if ($head.output.Trim() -ne $Config.vcpkg.commit -or $dirty.output.Trim() -or $shallow.output.Trim() -ne 'false') { throw 'vcpkg checkout is wrong, modified, or shallow.' }
    $metadata = Get-Content -LiteralPath (Join-Path $directory 'scripts/vcpkg-tool-metadata.txt') -Raw
    if ($metadata -notmatch ('VCPKG_TOOL_RELEASE_TAG=' + [regex]::Escape($Config.vcpkg.toolVersion))) { throw 'vcpkg executable release disagrees with checkout metadata.' }
    return $directory
}

function Set-CppPortableProcessEnvironment {
    param($Config, [string]$Root = $script:CppProjectRoot, [string]$LogRoot)
    foreach ($tool in $Config.portable) { Assert-CppPortable $tool (Get-CppChildPath (Join-Path $Root '.tools') $tool.directory) }
    $directory = Assert-CppVcpkg $Config $Root $LogRoot
    $cmake = $Config.portable | Where-Object id -eq 'cmake'
    $ninja = $Config.portable | Where-Object id -eq 'ninja'
    $cmakeExe = Join-Path (Join-Path $Root ".tools/$($cmake.directory)") $cmake.executable
    $ninjaExe = Join-Path (Join-Path $Root ".tools/$($ninja.directory)") $ninja.executable
    $downloads = Join-Path $Root '.tools/vcpkg-downloads'
    $binaryCache = Join-Path $Root '.tools/vcpkg-binary-cache'
    New-Item -ItemType Directory -Path $downloads,$binaryCache -Force | Out-Null
    $env:PATH = (Split-Path $cmakeExe) + ';' + (Split-Path $ninjaExe) + ';' + $directory + ';' + $env:PATH
    $env:VCPKG_ROOT = $directory
    $env:VCPKG_FORCE_SYSTEM_BINARIES = '1'
    [Environment]::SetEnvironmentVariable('VCPKG_FORCE_DOWNLOADED_BINARIES',$null,'Process')
    $env:VCPKG_DISABLE_METRICS = '1'
    $env:VCPKG_DOWNLOADS = $downloads
    $env:VCPKG_DEFAULT_BINARY_CACHE = $binaryCache
    $env:VSLANG = '1033'
    return [pscustomobject]@{ cmake=$cmakeExe; ninja=$ninjaExe; vcpkg=(Join-Path $directory 'vcpkg.exe') }
}

function Set-CppProcessEnvironment {
    param($Config, [string]$Root = $script:CppProjectRoot, [string]$LogRoot)
    $before = Get-CppEnvironment
    try {
        foreach ($tool in $Config.portable) { Assert-CppPortable $tool (Get-CppChildPath (Join-Path $Root '.tools') $tool.directory) }
        $vcpkg = Assert-CppVcpkg $Config $Root $LogRoot
        $vs = Get-CppVsInstance $Config
        if (-not $vs) { throw 'Locked Build Tools not installed; run setup-cpp.ps1.' }
        $system = Get-CppSystemInventory $Config $vs
        $receipt = Get-Content -LiteralPath (Join-Path $Root '.tools/cpp-system.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $manifestHash = (Get-FileHash -LiteralPath (Join-Path $Root 'config/windows-cpp-toolchain.json')).Hash
        if ($receipt.manifestSHA256 -ne $manifestHash -or $receipt.system.instance.instanceId -ne $vs.instanceId) { throw 'System receipt does not match manifest/VS instance.' }
        foreach ($file in $receipt.system.files) { Assert-CppHash $file.path $file.sha256 }
        # Use Microsoft's PowerShell API to avoid cmd.exe quoting/code-page conversion.
        $dev = Join-Path $vs.installationPath 'Common7/Tools/Microsoft.VisualStudio.DevShell.dll'
        $signature = Get-AuthenticodeSignature -LiteralPath $dev
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') { throw 'Invalid Microsoft developer shell signature.' }
        $system | Add-Member -NotePropertyName developerShell -NotePropertyValue @{path=$dev;sha256=(Get-FileHash -LiteralPath $dev).Hash;signer=$signature.SignerCertificate.Subject}
        foreach ($name in @('CL','_CL_','LINK','_LINK_','INCLUDE','LIB','LIBPATH','VSCMD_VER','VCPKG_FORCE_DOWNLOADED_BINARIES')) { [Environment]::SetEnvironmentVariable($name,$null,'Process') }
        Import-Module $dev -Scope Local -ErrorAction Stop
        Enter-VsDevShell -VsInstallPath $vs.installationPath -Arch amd64 -HostArch amd64 -SkipAutomaticLocation -DevCmdArguments ('-no_logo -winsdk=' + $Config.visualStudio.sdkKitVersion) -ErrorAction Stop | Out-Null
        $cmake = $Config.portable | Where-Object id -eq 'cmake'
        $ninja = $Config.portable | Where-Object id -eq 'ninja'
        $cmakeExe = Join-Path (Join-Path $Root ".tools/$($cmake.directory)") $cmake.executable
        $ninjaExe = Join-Path (Join-Path $Root ".tools/$($ninja.directory)") $ninja.executable
        $env:PATH = (Split-Path $cmakeExe) + ';' + (Split-Path $ninjaExe) + ';' + $vcpkg + ';' + $env:PATH
        $env:VCPKG_ROOT = $vcpkg
        $env:VCPKG_VISUAL_STUDIO_PATH = $vs.installationPath
        $env:VCPKG_FORCE_SYSTEM_BINARIES = '1'
        $env:VCPKG_DISABLE_METRICS = '1'
        $env:VCPKG_DOWNLOADS = Join-Path $Root '.tools/vcpkg-downloads'
        $env:VCPKG_DEFAULT_BINARY_CACHE = Join-Path $Root '.tools/vcpkg-binary-cache'
        $env:VSLANG = '1033'
        New-Item -ItemType Directory -Path $env:VCPKG_DOWNLOADS,$env:VCPKG_DEFAULT_BINARY_CACHE -Force | Out-Null
        if ((Get-Command cl.exe).Source -ne (Join-Path $system.vcDirectory 'bin/Hostx64/x64/cl.exe') -or $env:VSCMD_ARG_TGT_ARCH -ne 'x64') { throw 'Developer environment selected an unexpected compiler/architecture.' }
        return [pscustomobject]@{ system=$system; cmake=$cmakeExe; ninja=$ninjaExe; vcpkg=(Join-Path $vcpkg 'vcpkg.exe') }
    } catch { Restore-CppEnvironment $before; throw }
}

function Test-CppToolVersions {
    param($Config, $Tools, [string]$Root, [string]$LogRoot)
    $cmake = Invoke-CppCommand $Tools.cmake @('--version') $Root $LogRoot
    $ninja = Invoke-CppCommand $Tools.ninja @('--version') $Root $LogRoot
    $vcpkg = Invoke-CppCommand $Tools.vcpkg @('version') $Root $LogRoot
    if ($cmake.output -notmatch ('(?m)^cmake version ' + [regex]::Escape(($Config.portable | Where-Object id -eq 'cmake').version) + '\s*$') -or $ninja.output.Trim() -ne ($Config.portable | Where-Object id -eq 'ninja').version -or -not $vcpkg.output.Contains($Config.vcpkg.toolVersion)) { throw 'Executable version does not match the lock.' }
    foreach ($name in @('cmake','ninja')) {
        $resolved = Invoke-CppCommand $Tools.vcpkg @('fetch',$name) $Root $LogRoot
        if ($resolved.output.Trim() -ne $Tools.$name) { throw "vcpkg selected unexpected $name : $($resolved.output)" }
    }
    return @($cmake,$ninja,$vcpkg)
}
