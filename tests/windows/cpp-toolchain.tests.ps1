#requires -Version 5.1
<# .SYNOPSIS
Checks tool provenance, isolated faults and native C/C++ probes.
-PortableOnly explicitly skips MSVC/SDK/compilation and never reports T01 passed.
#>
[CmdletBinding()]
param([switch]$PortableOnly)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../../scripts/windows/cpp-common.ps1')
$root = $script:CppProjectRoot
$runId = 'g2-t01-tests-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
$run = Join-Path $root "out/runs/$runId"
$fixture = Join-Path $root ("out/tests/$runId/" + [string]::Concat([char]0x5DE5,[char]0x5177,' chain'))
New-Item -ItemType Directory -Path $run,$fixture -Force | Out-Null
$before = Get-CppEnvironment
$persistentBefore = @{ user=[Environment]::GetEnvironmentVariable('PATH','User'); machine=[Environment]::GetEnvironmentVariable('PATH','Machine') }
$result = [ordered]@{ started=(Get-Date -Format o); status='running'; portableOnly=[bool]$PortableOnly; inputs=@(Get-CppInputRecords $root); checks=@(); builds=@(); workingDirectory=(Get-Location).Path }
$code = 0

function Add-CppCheck {
    param([string]$Name, [scriptblock]$Action)
    Write-Host "Checking: $Name"
    & $Action
    $result.checks += @{ name=$Name; status='passed' }
}

function Invoke-CppSetupCheck {
    param([string]$Project, [string]$Directory, [string]$ExpectedError)
    $arguments = @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $Project 'scripts/windows/setup-cpp.ps1'),'-VerifyOnly')
    if ($PortableOnly) { $arguments += '-PortableOnly' }
    $command = Invoke-CppCommand 'powershell.exe' $arguments $Directory $run -AllowFailure
    if ($ExpectedError) {
        if ($command.exitCode -eq 0 -or $command.output -notmatch $ExpectedError) { throw "Wrong failure for $ExpectedError : $($command.output)" }
    } elseif ($command.exitCode -ne 0) { throw $command.output }
    $records = @(Get-ChildItem -LiteralPath (Join-Path $Project 'out/runs') -Directory -Filter 'g2-t01-setup-*' | Sort-Object Name)
    $recordPath = Join-Path $records[-1].FullName 'result.json'
    $receipt = Get-Content -LiteralPath $recordPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($ExpectedError -and $receipt.status -ne 'failed') { throw 'Missing failed setup receipt.' }
    $result.checks += @{ name='setup invocation'; status=$receipt.status; record=$recordPath; expectedFailure=[bool]$ExpectedError }
}

function Invoke-CppProbe {
    param($Tools, [string]$Source, [string]$Build, [string]$Generator)
    $configArgs = @('-S',$Source,'-B',$Build,'-G',$Generator)
    if ($Generator -eq 'Visual Studio 17 2022') {
        $configArgs += @('-A','x64','-T',('v143,host=x64,version=' + $Tools.system.vcVersion),('-DCMAKE_GENERATOR_INSTANCE=' + $Tools.system.instance.installationPath),('-DCMAKE_SYSTEM_VERSION=' + $Tools.system.sdkKitVersion))
    } else { $configArgs += @('-DCMAKE_BUILD_TYPE=Release',('-DCMAKE_MAKE_PROGRAM=' + $Tools.ninja)) }
    $null = Invoke-CppCommand $Tools.cmake $configArgs $env:TEMP $run
    $buildCommand = Invoke-CppCommand $Tools.cmake @('--build',$Build,'--config','Release','--verbose') $env:TEMP $run
    $ctest = Join-Path (Split-Path $Tools.cmake) 'ctest.exe'
    $null = Invoke-CppCommand $ctest @('--test-dir',$Build,'-C','Release','--output-on-failure') $env:TEMP $run
    $bin = $Build
    if ($Generator -eq 'Visual Studio 17 2022') { $bin = Join-Path $Build 'Release' }
    $dumpbin = Join-Path $Tools.system.vcDirectory 'bin/Hostx64/x64/dumpbin.exe'
    foreach ($name in @('c_probe','cpp_probe')) {
        $exe = Join-Path $bin ($name + '.exe')
        $ran = Invoke-CppCommand $exe @() $env:TEMP $run
        $expected = 'C_PROBE_OK x64 MD int64=9007199254740993'
        if ($name -eq 'cpp_probe') { $expected='CPP_PROBE_OK x64 MD c++14 int64=9007199254740993 threads=2000' }
        if ($ran.output.Trim() -ne $expected) { throw 'Unexpected probe result.' }
        $headers = Invoke-CppCommand $dumpbin @('/headers',$exe) $env:TEMP $run
        $dependents = Invoke-CppCommand $dumpbin @('/dependents',$exe) $env:TEMP $run
        if ($headers.output -notmatch '8664 machine' -or $dependents.output -match '(?i)(VCRUNTIME\d+D|MSVCP\d+D|ucrtbased)\.dll') { throw 'Wrong PE architecture or Debug CRT.' }
        if ($dependents.output -notmatch '(?i)(VCRUNTIME|api-ms-win-crt|ucrtbase)') { throw 'Expected dynamic CRT imports.' }
        $runtime=@()
        if ($name -eq 'cpp_probe') {
            $process=Start-Process -FilePath $exe -ArgumentList '--inspect-runtime' -WindowStyle Hidden -PassThru
            try {
                $deadline=(Get-Date).AddSeconds(4)
                do {
                    Start-Sleep -Milliseconds 100
                    $process.Refresh()
                    $modules=@($process.Modules | Where-Object { $_.ModuleName -match '^(ucrtbase|vcruntime140(_1)?|msvcp140)\.dll$' })
                } while ($modules.Count -lt 3 -and (Get-Date) -lt $deadline -and -not $process.HasExited)
                if ($modules.Count -lt 3) { throw 'Could not inspect the actual loaded dynamic CRT modules.' }
                foreach ($module in $modules) {
                    if (-not $module.FileName.StartsWith([Environment]::SystemDirectory + '\',[StringComparison]::OrdinalIgnoreCase)) { throw "Unexpected CRT load location: $($module.FileName)" }
                    $runtime+=@{name=$module.ModuleName;path=$module.FileName;version=$module.FileVersionInfo.FileVersion;sha256=(Get-FileHash -LiteralPath $module.FileName).Hash}
                }
                if (-not $process.WaitForExit(10000)) { throw 'Runtime inspection process did not exit normally.' }
                $process.Refresh()
                if ($process.ExitCode -ne 0) { throw 'Runtime inspection probe failed.' }
            } finally {
                if (-not $process.HasExited) { $process.Kill(); $process.WaitForExit() }
                $process.Dispose()
            }
        }
        $result.builds += @{ generator=$Generator; executable=$exe; sha256=(Get-FileHash -LiteralPath $exe).Hash; output=$ran.output; dependents=$dependents.output; loadedRuntime=$runtime }
    }
    if ($buildCommand.output -notmatch '[/\-]std:c\+\+14\b' -or $buildCommand.output -notmatch '[/\-]MD\b') { throw 'Compile command does not prove /std:c++14 and /MD.' }
}

try {
    $config = Read-CppConfig $root
    $result.manifestSHA256=(Get-FileHash -LiteralPath (Join-Path $root 'config/windows-cpp-toolchain.json')).Hash
    $result.gitHead=(Invoke-CppCommand 'git' @('rev-parse','HEAD') $root $run).output.Trim()
    Add-CppCheck 'versions, hashes and vcpkg tool resolution' {
        try {
            if ($PortableOnly) { $tools=Set-CppPortableProcessEnvironment $config $root $run }
            else { $tools=Set-CppProcessEnvironment $config $root $run }
            $result.versions=Test-CppToolVersions $config $tools $root $run
        } finally { Restore-CppEnvironment $before }
    }
    Add-CppCheck 'repeat preparation from another working directory' { Invoke-CppSetupCheck $root $env:TEMP }
    Add-CppCheck 'isolated Unicode and space path preparation' {
        New-Item -ItemType Directory -Path (Join-Path $fixture 'config'),(Join-Path $fixture 'scripts/windows'),(Join-Path $fixture '.tools/downloads'),(Join-Path $fixture 'tests') -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $root 'config/windows-cpp-toolchain.json') -Destination (Join-Path $fixture 'config')
        foreach ($file in @('cpp-common.ps1','setup-cpp.ps1','use-cpp.ps1')) { Copy-Item -LiteralPath (Join-Path $root "scripts/windows/$file") -Destination (Join-Path $fixture 'scripts/windows') }
        foreach ($tool in $config.portable) { Copy-Item -LiteralPath (Join-Path $root ".tools/$($tool.directory)") -Destination (Join-Path $fixture '.tools') -Recurse }
        Copy-Item -LiteralPath (Join-Path $root ".tools/$($config.vcpkg.directory)") -Destination (Join-Path $fixture '.tools') -Recurse
        Copy-Item -LiteralPath (Join-Path $root 'tests/cpp_toolchain') -Destination (Join-Path $fixture 'tests') -Recurse
        if (-not $PortableOnly) { Copy-Item -LiteralPath (Join-Path $root '.tools/cpp-system.json') -Destination (Join-Path $fixture '.tools') }
        # The ignored fixture remains inside the project checkout; record its parent HEAD.
        Invoke-CppSetupCheck $fixture $env:TEMP
    }
    $ninja = $config.portable | Where-Object id -eq 'ninja'
    $ninjaFile = Join-Path $fixture ".tools/$($ninja.directory)/$($ninja.executable)"
    $original = [IO.File]::ReadAllBytes($ninjaFile)
    Add-CppCheck 'corrupt extracted executable rejected' {
        try {
            [IO.File]::WriteAllBytes($ninjaFile,[byte[]]@(1,2,3))
            Invoke-CppSetupCheck $fixture $env:TEMP 'Checksum mismatch'
            $rejected=$false
            try { $null=Set-CppProcessEnvironment $config $fixture $run }
            catch { if ($_.Exception.Message -notmatch 'Checksum mismatch') { throw }; $rejected=$true }
            if (-not $rejected) { throw 'Activation accepted corrupt tools.' }
            $afterFailure=Get-CppEnvironment
            if ($before.Count -ne $afterFailure.Count) { throw 'Failed activation changed environment size.' }
            foreach ($key in $before.Keys) { if ($before[$key] -cne $afterFailure[$key]) { throw "Failed activation changed $key" } }
        }
        finally { [IO.File]::WriteAllBytes($ninjaFile,$original) }
    }
    Add-CppCheck 'missing executable rejected' {
        try { Remove-Item -LiteralPath $ninjaFile; Invoke-CppSetupCheck $fixture $env:TEMP 'Required file missing' }
        finally { [IO.File]::WriteAllBytes($ninjaFile,$original) }
    }
    Add-CppCheck 'manifest version mismatch rejected' {
        $path=Join-Path $fixture 'config/windows-cpp-toolchain.json'
        $bytes=[IO.File]::ReadAllBytes($path)
        try { $bad=Get-Content -LiteralPath $path -Raw | ConvertFrom-Json; ($bad.portable | Where-Object id -eq 'ninja').version='0.0.0'; Write-CppJson $bad $path; Invoke-CppSetupCheck $fixture $env:TEMP 'version mismatch' }
        finally { [IO.File]::WriteAllBytes($path,$bytes) }
    }
    Add-CppCheck 'corrupt cached archive rejected' {
        $cache=Join-Path $fixture ".tools/downloads/$($ninja.archive)"
        try { [IO.File]::WriteAllBytes($cache,[byte[]]@(1,2,3)); Invoke-CppSetupCheck $fixture $env:TEMP 'Checksum mismatch' }
        finally { Remove-Item -LiteralPath $cache }
    }
    Add-CppCheck 'modified vcpkg checkout rejected' {
        $path=Join-Path $fixture ".tools/$($config.vcpkg.directory)/scripts/vcpkg-tool-metadata.txt"
        $bytes=[IO.File]::ReadAllBytes($path)
        try { Add-Content -LiteralPath $path -Value '# isolated fault'; Invoke-CppSetupCheck $fixture $env:TEMP 'vcpkg checkout' }
        finally { [IO.File]::WriteAllBytes($path,$bytes) }
    }
    if (-not $PortableOnly) {
        Add-CppCheck 'Release x64 C/C++ with VS and Ninja' {
            try {
                $tools=Set-CppProcessEnvironment $config $root $run
                $result.system=$tools.system
                $result.environment=@{ INCLUDE=$env:INCLUDE; LIB=$env:LIB; LIBPATH=$env:LIBPATH; VCToolsVersion=$env:VCToolsVersion; WindowsSDKVersion=$env:WindowsSDKVersion }
                Invoke-CppProbe $tools (Join-Path $root 'tests/cpp_toolchain') (Join-Path $root "out/build/cpp-probe/$runId/vs") 'Visual Studio 17 2022'
                Invoke-CppProbe $tools (Join-Path $root 'tests/cpp_toolchain') (Join-Path $root "out/build/cpp-probe/$runId/ninja") 'Ninja'
                $tools=Set-CppProcessEnvironment $config $fixture $run
                Invoke-CppProbe $tools (Join-Path $fixture 'tests/cpp_toolchain') (Join-Path $fixture 'out/build/vs') 'Visual Studio 17 2022'
                Invoke-CppProbe $tools (Join-Path $fixture 'tests/cpp_toolchain') (Join-Path $fixture 'out/build/ninja') 'Ninja'
            } finally { Restore-CppEnvironment $before }
        }
    }
    Add-CppCheck 'environment restored and outputs ignored' {
        $after=Get-CppEnvironment
        if ($before.Count -ne $after.Count) {
            $added=@($after.Keys | Where-Object { -not $before.ContainsKey($_) })
            $removed=@($before.Keys | Where-Object { -not $after.ContainsKey($_) })
            throw "Process environment size changed. Added: $added; removed: $removed"
        }
        foreach ($key in $before.Keys) { if ($before[$key] -cne $after[$key]) { throw "Process environment changed: $key" } }
        foreach ($scope in @('User','Machine')) { if ([Environment]::GetEnvironmentVariable('PATH',$scope) -cne $persistentBefore[$scope.ToLowerInvariant()]) { throw 'Persistent PATH changed.' } }
        $null=Invoke-CppCommand 'git' @('check-ignore','.tools/cpp-system.json',"out/runs/$runId/result.json") $root $run
    }
    $result.status='passed'
    if ($PortableOnly) { $result.status='portable-passed'; $result.notValidated=@('MSVC installation','SDK/CRT provenance','C/C++ compilation/link/run','VS and Ninja build generators','Unicode build/run') }
} catch { $result.status='failed'; $result.error=$_.Exception.Message; Write-Host "FAILED: $($result.error)"; $code=1 }
finally {
    Restore-CppEnvironment $before
    $result.finished=Get-Date -Format o
    Write-CppJson $result (Join-Path $run 'result.json')
    Write-Host "Validation record: $run"
}
exit $code
