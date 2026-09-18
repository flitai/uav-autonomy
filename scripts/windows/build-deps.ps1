#requires -Version 5.1
[CmdletBinding()]
param([switch]$Rebuild)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'deps-common.ps1')
$root=$script:CppProjectRoot
$runId='g2-t02-build-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff')
$run=Join-Path $root "out/runs/$runId"
$build=Join-Path $root ("out/build/deps/$runId/"+[string]::Concat([char]0x4F9D,[char]0x8D56,' build'))
$installed=Join-Path $build 'installed'
New-Item -ItemType Directory -Path $run,$build -Force | Out-Null
$before=Get-CppEnvironment
$result=[ordered]@{schemaVersion=1;runId=$runId;status='running';started=(Get-Date -Format o);inputs=@(Get-DepsInputs);rebuild=[bool]$Rebuild;triplet='x64-windows-uxas';workingDirectory=(Get-Location).Path;buildDirectory=$build;installRoot=$installed}
$code=0
try {
    $cfg=Read-CppConfig; $tools=Set-CppProcessEnvironment $cfg $root $run
    $result.tools=$tools; $result.versions=Test-CppToolVersions $cfg $tools $root $run
    $result.hostTools=@(Set-DepsHostTools $tools $run)
    $null=Test-CppToolVersions $cfg $tools $root $run
    $result.gitHead=(Invoke-CppCommand git @('rev-parse','HEAD') $root $run).output.Trim()
    $lock=Get-Content -Raw -Encoding UTF8 (Join-Path $root 'config/windows-dependencies.json') | ConvertFrom-Json
    Assert-DepsSourceDownloads $env:VCPKG_DOWNLOADS $lock
    $env:VCPKG_BINARY_SOURCES='clear;files,'+(Join-Path $root '.tools/vcpkg-binary-cache')+',readwrite'
    if($Rebuild) { $env:VCPKG_BINARY_SOURCES='clear;files,'+(Join-Path $root '.tools/vcpkg-binary-cache')+',write' }
    $env:VCPKG_MAX_CONCURRENCY='8'
    $env:VCPKG_VISUAL_STUDIO_PATH=$tools.system.instance.installationPath
    $result.cache=@{mode=$(if($Rebuild){'write-only'}else{'readwrite'});phases=@()}
    $base=@('--triplet=x64-windows-uxas','--host-triplet=x64-windows-uxas',"--x-install-root=$installed",("--x-buildtrees-root="+(Join-Path $build 'buildtrees')),("--x-packages-root="+(Join-Path $build 'packages')),("--overlay-ports="+(Join-Path $root 'config/vcpkg/ports')),("--overlay-triplets="+(Join-Path $root 'config/vcpkg/triplets')))
    $allowed=@((@($lock.directDependencies)+@($lock.historicalBoostPorts.PSObject.Properties.Name)+@('vcpkg-cmake','vcpkg-cmake-config')) | Sort-Object -Unique)
    foreach($phase in @('non-boost','all')) {
        $manifestDir=Join-Path $build "manifests/$phase"
        New-Item -ItemType Directory -Path $manifestDir -Force | Out-Null
        $manifest=Get-Content -Raw -Encoding UTF8 (Join-Path $root 'vcpkg.json') | ConvertFrom-Json
        if($phase -eq 'non-boost') { $manifest.dependencies=@($manifest.dependencies | Where-Object name -notlike 'boost-*') }
        Write-CppJson $manifest (Join-Path $manifestDir 'vcpkg.json')
        $arguments=@('install',"--x-manifest-root=$manifestDir")+$base
        Write-Host "Resolving dependency phase: $phase"
        $plan=Invoke-CppCommand $tools.vcpkg ($arguments+@('--dry-run')) $env:TEMP $run
        $names=@([regex]::Matches($plan.output,'(?m)^\s*\*?\s*([a-z0-9-]+)(?:\[[^\]]+\])?:x64-windows-uxas') | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique)
        if(-not $names.Count) { throw 'Dependency plan could not be inspected.' }
        foreach($name in $names) { if($name -notin $allowed) { throw "Unregistered dependency: $name" } }
        $result[($phase+'Plan')]=$names
        Write-Host "Building dependency phase: $phase ($($names.Count) ports); logs: $build"
        $built=Invoke-CppCommand $tools.vcpkg $arguments $env:TEMP $run
        $restored=[regex]::Match($built.output,'Restored ([0-9]+) package\(s\)')
        $count=0;if($restored.Success) { $count=[int]$restored.Groups[1].Value }
        if($Rebuild -and $count) { throw 'Rebuild unexpectedly read binary cache.' }
        $result.cache.phases+=@{name=$phase;restored=$count}
        [IO.File]::WriteAllText((Join-Path $run "$phase.log"),$built.output,(New-Object Text.UTF8Encoding($false)))
    }
    $prefix=Join-Path $installed 'x64-windows-uxas'
    Add-DepsCMakePackage $prefix
    Assert-DepsInputs $result.inputs
    $result.prefix=$prefix; $result.files=@(Get-DepsFiles $prefix)
    $result.packageStatus=[IO.File]::ReadAllText((Join-Path $installed 'vcpkg/status'))
    $result.sources=@(foreach($spdxFile in (Get-ChildItem -LiteralPath (Join-Path $prefix 'share') -Filter 'vcpkg.spdx.json' -Recurse -File)) {
        $spdx=Get-Content -Raw -Encoding UTF8 $spdxFile.FullName | ConvertFrom-Json
        @{port=$spdxFile.Directory.Name;identity=$spdx.name;packages=@($spdx.packages);sha256=(Get-FileHash -LiteralPath $spdxFile.FullName).Hash}
    })
    if($result.sources.Count -ne $allowed.Count) { throw 'Installed port inventory differs from the locked graph.' }
    Assert-DepsSourceDownloads $env:VCPKG_DOWNLOADS $lock
    $result.supportDownloads=$lock.supportDownloads
    $result.status='candidate'
    Write-CppJson $result (Join-Path $build 'build-info.json')
    Write-Host "Dependency candidate ready: $runId"
} catch { $code=1; $result.status='failed';$result.error=$_.Exception.Message;Write-Host "FAILED: $($result.error)" }
finally { Restore-CppEnvironment $before; $result.finished=Get-Date -Format o; Write-CppJson $result (Join-Path $run 'result.json'); Write-Host "Build record: $run" }
exit $code
