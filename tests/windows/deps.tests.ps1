#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory=$true)][ValidatePattern('^g2-t02-build-[0-9-]+$')][string]$BuildRunId)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../scripts/windows/deps-common.ps1')
$root=$script:CppProjectRoot
$runId='g2-t02-tests-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff')
$run=Join-Path $root "out/runs/$runId"
$fixture=Join-Path $root "out/tests/$runId"
New-Item -ItemType Directory -Path $run,$fixture -Force | Out-Null
$before=Get-CppEnvironment
$persistent=@{user=[Environment]::GetEnvironmentVariable('PATH','User');machine=[Environment]::GetEnvironmentVariable('PATH','Machine')}
$pointer=Join-Path $root 'out/artifacts/deps/current.json'
$oldPointer=$null
if(Test-Path -LiteralPath $pointer) { $oldPointer=[IO.File]::ReadAllBytes($pointer) }
$result=[ordered]@{schemaVersion=1;runId=$runId;buildRunId=$BuildRunId;status='running';started=(Get-Date -Format o);checks=@();probes=@();inputs=@()}
foreach($file in @('tests/windows/deps.tests.ps1','tests/dependencies/CMakeLists.txt','tests/dependencies/deps_probe.cpp','tests/dependencies/spdx.tests.cmake')) { $result.inputs+=@{path=$file;sha256=(Get-FileHash -LiteralPath (Join-Path $root $file)).Hash} }
$code=0
function Check-Deps {
    param([string]$Name,[scriptblock]$Action)
    Write-Host "Checking: $Name"; & $Action; $result.checks+=@{name=$Name;status='passed'}
}
function Expect-DepsFailure {
    param([scriptblock]$Action,[string]$Pattern)
    $caught=$false
    try { & $Action } catch { if($_.Exception.Message -notmatch $Pattern) { throw }; $caught=$true }
    if(-not $caught) { throw "Expected failure was not rejected: $Pattern" }
}
function Run-DepsConsumer {
    param([string]$Prefix,[string]$Label,[string]$Generator)
    $dir=Join-Path $root "out/build/deps-probes/$runId/$Label"
    $args=@('-S',(Join-Path $root 'tests/dependencies'),'-B',$dir,'-G',$Generator,"-DUXAS_DEPENDENCIES_PREFIX=$Prefix")
    if($Generator -eq 'Ninja') { $args+=@('-DCMAKE_BUILD_TYPE=Release',"-DCMAKE_MAKE_PROGRAM=$($tools.ninja)") }
    else { $args+=@('-A','x64','-T',('v143,host=x64,version='+$tools.system.vcVersion),('-DCMAKE_GENERATOR_INSTANCE='+$tools.system.instance.installationPath),'-DCMAKE_SYSTEM_VERSION=10.0.26100.0') }
    $null=Invoke-CppCommand $tools.cmake $args $env:TEMP $run
    $built=Invoke-CppCommand $tools.cmake @('--build',$dir,'--config','Release','--verbose') $env:TEMP $run
    if($built.output -notmatch '[/\-]std:c\+\+14\b' -or $built.output -notmatch '[/\-]MD\b') { throw 'Consumer compile options were not proven.' }
    $headerEvidence=$built.output
    if($Generator -eq 'Ninja') {
        $depOutput=(Invoke-CppCommand $tools.ninja @('-C',$dir,'-t','deps') $env:TEMP $run).output
        $headerEvidence=(@(foreach($line in ($depOutput -split "`n")) {
            if($line -match '^\s+\S') {
                $path=$line.Trim();if(-not [IO.Path]::IsPathRooted($path)) { $path=Join-Path $dir $path }
                [IO.Path]::GetFullPath($path)
            }
        }) -join "`n")
    }
    foreach($header in @('zmq.hpp','czmq.h','pugixml.hpp','SQLiteCpp','boost')) {
        if($headerEvidence.Replace('\','/') -notmatch ([regex]::Escape($Prefix.Replace('\','/'))+'/include/.*'+[regex]::Escape($header))) { throw "Missing header source evidence: $header" }
    }
    $exe=Join-Path $dir 'deps_probe.exe';if($Generator -ne 'Ninja') { $exe=Join-Path $dir 'Release/deps_probe.exe' }
    $ctest=Join-Path (Split-Path $tools.cmake) 'ctest.exe'
    $null=Invoke-DepsBounded $ctest @('--test-dir',$dir,'-C','Release','--output-on-failure') $env:TEMP $run 90
    foreach($component in @('zmq','pugi','sqlite','boost')) {
        $record=Invoke-DepsBounded $exe @($component) $run $run 20
        if($record.output.Trim() -ne "DEPS_OK $component x64 MD c++14") { throw 'Probe output mismatch.' }
        $result.probes+=@{label=$Label;generator=$Generator;component=$component;output=$record.output.Trim();exitCode=$record.exitCode;executable=$exe;sha256=(Get-FileHash -LiteralPath $exe).Hash}
    }
    $dumpbin=Join-Path $tools.system.vcDirectory 'bin/Hostx64/x64/dumpbin.exe'
    $headers=Invoke-CppCommand $dumpbin @('/headers',$exe) $run $run
    $deps=Invoke-CppCommand $dumpbin @('/dependents',$exe) $run $run
    if($headers.output -notmatch '8664 machine' -or $deps.output -notmatch 'VCRUNTIME140.dll' -or $deps.output -match '(?i)(ucrtbased|vcruntime140d|msvcp140d|libzmq|czmq|sqlite|pugixml|boost).*\.dll') { throw 'Consumer architecture/CRT/static library mismatch.' }
    return $exe
}
try {
    $info=Get-Content -Raw -Encoding UTF8 (Join-Path $root "out/runs/$BuildRunId/result.json") | ConvertFrom-Json
    Check-Deps 'candidate provenance and package integrity' { Assert-DepsPackage $info.prefix $info }
    $cfg=Read-CppConfig;$tools=Set-CppProcessEnvironment $cfg $root $run
    $null=Test-CppToolVersions $cfg $tools $root $run
    Check-Deps 'CMake 3.31 SPDX JSON compatibility' { $null=Invoke-CppCommand $tools.cmake @('-P',(Join-Path $root 'tests/dependencies/spdx.tests.cmake')) $env:TEMP $run }
    Check-Deps 'native consumers with VS and Ninja from other working directory' {
        $script:probeExe=Run-DepsConsumer $info.prefix 'vs' 'Visual Studio 17 2022'
        $unicode=[string]::Concat([char]0x6D4B,[char]0x8BD5,' ninja')
        $null=Run-DepsConsumer $info.prefix $unicode 'Ninja'
    }
    Check-Deps 'all installed static libraries use the release dynamic CRT' {
        $dumpbin=Join-Path $tools.system.vcDirectory 'bin/Hostx64/x64/dumpbin.exe'
        foreach($lib in (Get-ChildItem -LiteralPath (Join-Path $info.prefix 'lib') -Filter '*.lib' -File)) {
            $r=Invoke-CppCommand $dumpbin @('/directives',$lib.FullName) $run $run
            if($r.output -match '(?i)DEFAULTLIB:\s*"?(LIBCMTD?|MSVCRTD|LIBCPMTD?)\b') { throw "Forbidden CRT directive: $($lib.Name)" }
        }
    }
    Check-Deps 'actual runtime modules and normal exit' {
        $p=Start-Process -FilePath $script:probeExe -ArgumentList runtime -WorkingDirectory $run -WindowStyle Hidden -PassThru
        try {
            $null=$p.Handle
            Start-Sleep -Milliseconds 400;$p.Refresh()
            $modules=@($p.Modules | Where-Object ModuleName -match '^(msvcp140|vcruntime140(_1)?|ucrtbase)\.dll$')
            if($modules.Count -lt 3) { throw 'Runtime modules missing.' }
            $result.runtime=@(foreach($module in $modules) {
                if(-not $module.FileName.StartsWith([Environment]::SystemDirectory+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected CRT module source.' }
                @{path=$module.FileName;version=$module.FileVersionInfo.FileVersion;sha256=(Get-FileHash -LiteralPath $module.FileName).Hash}
            })
            if(-not $p.WaitForExit(10000)) { throw 'Runtime probe did not exit.' };$p.Refresh();if($p.ExitCode -ne 0) { throw 'Runtime probe failed.' }
        } finally { if(-not $p.HasExited) { $p.Kill();$p.WaitForExit() };$p.Dispose() }
    }
    Check-Deps 'isolated missing and corrupt library rejected' {
        $copy=Join-Path $fixture 'package';Copy-Item -LiteralPath $info.prefix -Destination $copy -Recurse
        $library=Join-Path $copy 'lib/sqlite3.lib';$bytes=[IO.File]::ReadAllBytes($library)
        try {
            Remove-Item -LiteralPath $library
            Expect-DepsFailure { Assert-DepsPackage $copy $info } 'Required file missing'
            [IO.File]::WriteAllBytes($library,[byte[]]@(1,2,3))
            Expect-DepsFailure { Assert-DepsPackage $copy $info } 'Checksum mismatch'
        } finally { [IO.File]::WriteAllBytes($library,$bytes) }
    }
    Check-Deps 'isolated recipe/tool metadata changes rejected' {
        $copyRoot=Join-Path $fixture 'project';New-Item -ItemType Directory -Path $copyRoot | Out-Null
        foreach($input in $info.inputs) { $dest=Get-CppChildPath $copyRoot $input.path;New-Item -ItemType Directory -Path (Split-Path $dest) -Force | Out-Null;Copy-Item -LiteralPath (Join-Path $root $input.path) -Destination $dest }
        foreach($relative in @('config/windows-cpp-toolchain.json','config/vcpkg/ports/sqlite3/portfile.cmake')) {
            $path=Join-Path $copyRoot $relative;$bytes=[IO.File]::ReadAllBytes($path)
            try { [IO.File]::AppendAllText($path,' changed');Expect-DepsFailure { Assert-DepsInputs $info.inputs $copyRoot } 'Checksum mismatch' }
            finally { [IO.File]::WriteAllBytes($path,$bytes) }
        }
        $bad=($info | ConvertTo-Json -Depth 15 | ConvertFrom-Json);$bad.triplet='x86-windows'
        Expect-DepsFailure { Assert-DepsPackage $info.prefix $bad } 'metadata status/triplet mismatch'
    }
    Check-Deps 'isolated source checksum failure and timeout rejected' {
        $lock=Get-Content -Raw -Encoding UTF8 (Join-Path $root 'config/windows-dependencies.json') | ConvertFrom-Json
        $bad=Join-Path $fixture $lock.sources.sqlite3.archive;[IO.File]::WriteAllBytes($bad,[byte[]]@(0,1,2))
        Expect-DepsFailure { Assert-DepsSourceDownloads $fixture $lock } 'Source checksum mismatch'
        $timed=Invoke-DepsBounded $script:probeExe @('timeout') $run $run 1 -AllowFailure
        if(-not $timed.timedOut) { throw 'Timeout not detected.' }
        if(Get-Process -Id $timed.pid -ErrorAction SilentlyContinue) { throw 'Timed out owned process remains.' }
    }
    Check-Deps 'failure checks preserved the previous qualified pointer' {
        if($null -eq $oldPointer) { if(Test-Path -LiteralPath $pointer) { throw 'Failure published a pointer.' } }
        elseif([Convert]::ToBase64String([IO.File]::ReadAllBytes($pointer)) -ne [Convert]::ToBase64String($oldPointer)) { throw 'Failure replaced old pointer.' }
    }
    Check-Deps 'relocated package consumption' {
        $script:published=Get-CppChildPath (Join-Path $root 'out/artifacts/deps') "$BuildRunId/$runId"
        if(Test-Path -LiteralPath $script:published) { throw 'This batch is already published; preserve it and use a new build batch.' }
        New-Item -ItemType Directory -Path (Split-Path $script:published) -Force | Out-Null
        Copy-Item -LiteralPath $info.prefix -Destination $script:published -Recurse
        Assert-DepsPackage $script:published $info
        $null=Run-DepsConsumer $script:published 'relocated-vs' 'Visual Studio 17 2022'
        $null=Run-DepsConsumer $script:published 'relocated-ninja' 'Ninja'
    }
    Check-Deps 'environment restored and artifacts ignored' {
        Restore-CppEnvironment $before;$after=Get-CppEnvironment
        if($before.Count -ne $after.Count) { throw 'Environment size changed.' }
        foreach($key in $before.Keys) { if($before[$key] -cne $after[$key]) { throw "Environment changed: $key" } }
        foreach($scope in @('User','Machine')) { if([Environment]::GetEnvironmentVariable('PATH',$scope) -cne $persistent[$scope.ToLowerInvariant()]) { throw 'Persistent PATH changed.' } }
        $null=Invoke-CppCommand git @('check-ignore',$script:published,$run) $root $run
    }
    Assert-DepsInputs $result.inputs
    $info.status='passed';$info.prefix=$script:published;$info | Add-Member -NotePropertyName validationRunId -NotePropertyValue $runId
    Write-CppJson $info (Join-Path $script:published 'build-info.json')
    $next=$pointer+'.'+[Guid]::NewGuid().ToString('N')+'.tmp'
    Write-CppJson @{schemaVersion=1;buildRunId=$BuildRunId;validationRunId=$runId;prefix=$script:published;buildInfoSHA256=(Get-FileHash -LiteralPath (Join-Path $script:published 'build-info.json')).Hash} $next
    if(Test-Path -LiteralPath $pointer) {
        # PS5.1 marshals $null to an empty string for this overload. A real,
        # unique backup path both avoids that error and retains the old pointer.
        [IO.File]::Replace($next,$pointer,($pointer+'.previous-'+[Guid]::NewGuid().ToString('N')+'.json'))
    } else { [IO.File]::Move($next,$pointer) }
    $result.status='passed';$result.published=$script:published
} catch { $code=1;$result.status='failed';$result.error=$_.Exception.Message;Write-Host "FAILED: $($result.error)" }
finally { Restore-CppEnvironment $before;$result.finished=Get-Date -Format o;Write-CppJson $result (Join-Path $run 'result.json');Write-Host "Validation record: $run" }
exit $code
