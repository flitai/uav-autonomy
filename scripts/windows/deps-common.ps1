#requires -Version 5.1
. (Join-Path $PSScriptRoot 'cpp-common.ps1')

function Get-DepsInputs {
    param([string]$Root=$script:CppProjectRoot)
    $files=@('vcpkg.json','vcpkg-configuration.json','config/windows-dependencies.json','config/windows-cpp-toolchain.json','scripts/windows/cpp-common.ps1','scripts/windows/deps-common.ps1','scripts/windows/build-deps.ps1')
    $files+=@(Get-ChildItem -LiteralPath (Join-Path $Root 'config/vcpkg') -Recurse -File | ForEach-Object { $_.FullName.Substring($Root.Length+1).Replace('\','/') })
    foreach($file in ($files | Sort-Object -Unique)) { @{path=$file;sha256=(Get-FileHash -LiteralPath (Join-Path $Root $file)).Hash} }
}

function Set-DepsHostTools {
    param($Tools,[string]$LogRoot)
    $root=$script:CppProjectRoot
    $metadataPath=Join-Path (Split-Path $Tools.vcpkg) 'scripts/vcpkg-tools.json'
    $metadata=Get-Content -Raw -Encoding UTF8 $metadataPath | ConvertFrom-Json
    $lock=Get-Content -Raw -Encoding UTF8 (Join-Path $root 'config/windows-dependencies.json') | ConvertFrom-Json
    $records=@()
    foreach($name in @('powershell-core','7zip')) {
        # Only this named host tool may be downloaded; CMake/Ninja remain pinned.
        $forced=$env:VCPKG_FORCE_SYSTEM_BINARIES
        $downloaded=$env:VCPKG_FORCE_DOWNLOADED_BINARIES
        try {
            [Environment]::SetEnvironmentVariable('VCPKG_FORCE_SYSTEM_BINARIES',$null,'Process')
            $env:VCPKG_FORCE_DOWNLOADED_BINARIES='1'
            $fetched=Invoke-CppCommand $Tools.vcpkg @('fetch',$name) $root $LogRoot
        } finally { $env:VCPKG_FORCE_SYSTEM_BINARIES=$forced; [Environment]::SetEnvironmentVariable('VCPKG_FORCE_DOWNLOADED_BINARIES',$downloaded,'Process') }
        $path=($fetched.output.Trim() -split "`n")[-1].Trim()
        if(-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Cannot locate fetched host tool: $name" }
        if(-not $path.StartsWith($env:VCPKG_DOWNLOADS+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Unpinned system host tool selected.' }
        $entry=$lock.hostTools | Where-Object name -eq $name
        $meta=$metadata.tools | Where-Object { $_.name -eq $name -and $_.os -eq 'windows' -and $_.arch -in @('amd64','x64') }
        if($entry.sha512 -ne $meta.sha512 -or $entry.version -ne $meta.version) { throw 'Host tool metadata differs from lock.' }
        $archive=Join-Path $env:VCPKG_DOWNLOADS $entry.archive
        if((Get-FileHash -LiteralPath $archive -Algorithm SHA512).Hash -ne $entry.sha512) { throw "Host archive checksum mismatch: $name" }
        $directory=Split-Path $path
        foreach($file in $entry.files) { Assert-CppHash (Get-CppChildPath $directory $file.path) $file.sha256 }
        $receiptPath=Join-Path $directory '.uxas-host-tool.json'
        if(Test-Path -LiteralPath $receiptPath) {
            $receipt=Get-Content -Raw -Encoding UTF8 $receiptPath | ConvertFrom-Json
            if($receipt.sha512 -ne $entry.sha512) { throw 'Host tool receipt source mismatch.' }
            foreach($file in $receipt.files) { Assert-CppHash (Get-CppChildPath $directory $file.path) $file.sha256 }
        } else {
            # vcpkg verifies the pinned archive on first extraction; thereafter
            # reject changed extracted support files as well as the executable.
            $receipt=@{sha512=$entry.sha512;files=@(Get-DepsFiles $directory)}
            Write-CppJson $receipt $receiptPath
        }
        $env:PATH=(Split-Path $path)+';'+$env:PATH
        $versionArguments=@('--version');if($name -eq '7zip') { $versionArguments=@('i') }
        $version=Invoke-CppCommand $path $versionArguments $root $LogRoot
        if($version.output -notmatch [regex]::Escape($entry.version)) { throw 'Host executable version mismatch.' }
        $records+=@{name=$name;path=$path;sha256=(Get-FileHash -LiteralPath $path).Hash;source=$entry;receiptSHA256=(Get-FileHash -LiteralPath $receiptPath).Hash;metadataSHA256=(Get-FileHash -LiteralPath $metadataPath).Hash}
    }
    return $records
}

function Assert-DepsInputs {
    param($Records,[string]$Root=$script:CppProjectRoot)
    foreach($record in $Records) { Assert-CppHash (Get-CppChildPath $Root $record.path) $record.sha256 }
}

function Assert-DepsSourceDownloads {
    param([string]$Downloads,$Lock)
    foreach($source in (@($Lock.sources.PSObject.Properties | ForEach-Object Value)+@($Lock.supportDownloads))) {
        $path=Get-CppChildPath $Downloads $source.archive
        if(Test-Path -LiteralPath $path) {
            if((Get-FileHash -LiteralPath $path -Algorithm SHA512).Hash -ne $source.sha512) { throw "Source checksum mismatch: $path" }
        }
    }
}

function Resolve-DepsPackage {
    param([string]$Root=$script:CppProjectRoot)
    $pointer=Get-Content -Raw -Encoding UTF8 (Join-Path $Root 'out/artifacts/deps/current.json') | ConvertFrom-Json
    $prefix=Get-CppChildPath (Join-Path $Root 'out/artifacts/deps') "$($pointer.buildRunId)/$($pointer.validationRunId)"
    $metadata=Join-Path $prefix 'build-info.json'
    Assert-CppHash $metadata $pointer.buildInfoSHA256
    $info=Get-Content -Raw -Encoding UTF8 $metadata | ConvertFrom-Json
    $validation=Get-Content -Raw -Encoding UTF8 (Join-Path $Root "out/runs/$($pointer.validationRunId)/result.json") | ConvertFrom-Json
    if($info.status -ne 'passed' -or $validation.status -ne 'passed' -or $info.runId -ne $pointer.buildRunId -or $validation.buildRunId -ne $pointer.buildRunId -or $info.validationRunId -ne $pointer.validationRunId) { throw 'Dependency publication/validation identity mismatch.' }
    Assert-DepsPackage $prefix $info $Root
    Assert-DepsInputs $validation.inputs $Root
    return $prefix
}

function Get-DepsFiles {
    param([string]$Prefix)
    foreach($file in (Get-ChildItem -LiteralPath $Prefix -Recurse -File | Sort-Object FullName)) {
        @{path=$file.FullName.Substring($Prefix.TrimEnd('\').Length+1).Replace('\','/');sha256=(Get-FileHash -LiteralPath $file.FullName).Hash}
    }
}

function Assert-DepsPackage {
    param([string]$Prefix,$Info,[string]$Root=$script:CppProjectRoot)
    if($Info.status -notin @('candidate','passed') -or $Info.triplet -ne 'x64-windows-uxas') { throw 'Dependency metadata status/triplet mismatch.' }
    Assert-DepsInputs $Info.inputs $Root
    $currentInputs=@(Get-DepsInputs $Root | ForEach-Object { $_.path } | Sort-Object)
    $recordedInputs=@($Info.inputs | ForEach-Object { $_.path } | Sort-Object)
    if(($currentInputs -join "`n") -cne ($recordedInputs -join "`n")) { throw 'Dependency input inventory changed.' }
    if(-not $Info.files.Count) { throw 'Dependency file inventory is empty.' }
    $actual=@(Get-ChildItem -LiteralPath $Prefix -Recurse -File | ForEach-Object { $_.FullName.Substring($Prefix.TrimEnd('\').Length+1).Replace('\','/') } | Where-Object { $_ -ne 'build-info.json' } | Sort-Object)
    $recorded=@($Info.files | ForEach-Object { $_.path } | Sort-Object)
    # Check individual entries first so missing/corrupt files retain precise diagnostics.
    foreach($file in $Info.files) { Assert-CppHash (Get-CppChildPath $Prefix $file.path) $file.sha256 }
    if(($actual -join "`n") -cne ($recorded -join "`n")) { throw 'Dependency file inventory changed.' }
}

function Add-DepsCMakePackage {
    param([string]$Prefix)
    $cmake=@('# Generated from the validated candidate; all paths are prefix-relative.','get_filename_component(_uxas_prefix "${CMAKE_CURRENT_LIST_DIR}/../.." ABSOLUTE)')
    foreach($entry in @(@('zeromq','libzmq*.lib'),@('czmq','czmq.lib'),@('pugixml','pugixml.lib'),@('sqlite3','sqlite3.lib'),@('sqlitecpp','SQLiteCpp.lib'))) {
        $libs=@(Get-ChildItem -LiteralPath (Join-Path $Prefix 'lib') -Filter $entry[1] -File)
        if($libs.Count -ne 1) { throw "Ambiguous or missing dependency library: $($entry[0])" }
        $name=$entry[0]
        $cmake+='if(NOT TARGET UxasDeps::'+$name+')'
        $cmake+='  add_library(UxasDeps::'+$name+' STATIC IMPORTED)'
        $cmake+='  set_target_properties(UxasDeps::'+$name+' PROPERTIES IMPORTED_LOCATION "${_uxas_prefix}/lib/'+$libs[0].Name+'" INTERFACE_INCLUDE_DIRECTORIES "${_uxas_prefix}/include")'
        $cmake+='endif()'
    }
    $cmake+=@('set_property(TARGET UxasDeps::zeromq PROPERTY INTERFACE_COMPILE_DEFINITIONS ZMQ_STATIC)',
        'set_property(TARGET UxasDeps::zeromq PROPERTY INTERFACE_LINK_LIBRARIES "ws2_32;iphlpapi;rpcrt4")',
        'set_property(TARGET UxasDeps::czmq PROPERTY INTERFACE_COMPILE_DEFINITIONS "CZMQ_STATIC;ZMQ_STATIC")',
        'set_property(TARGET UxasDeps::czmq PROPERTY INTERFACE_LINK_LIBRARIES "UxasDeps::zeromq;ws2_32;iphlpapi;rpcrt4")',
        'set_property(TARGET UxasDeps::sqlite3 PROPERTY INTERFACE_COMPILE_DEFINITIONS SQLITE_ENABLE_COLUMN_METADATA)',
        'set_property(TARGET UxasDeps::sqlitecpp PROPERTY INTERFACE_LINK_LIBRARIES UxasDeps::sqlite3)',
        'if(NOT TARGET UxasDeps::cppzmq)', '  add_library(UxasDeps::cppzmq INTERFACE IMPORTED)',
        '  set_property(TARGET UxasDeps::cppzmq PROPERTY INTERFACE_LINK_LIBRARIES UxasDeps::zeromq)','endif()',
        'if(NOT TARGET UxasDeps::boost)','  add_library(UxasDeps::boost INTERFACE IMPORTED)',
        '  set_target_properties(UxasDeps::boost PROPERTIES INTERFACE_INCLUDE_DIRECTORIES "${_uxas_prefix}/include" INTERFACE_COMPILE_DEFINITIONS BOOST_ALL_NO_LIB)','endif()')
    $boost=@(Get-ChildItem -LiteralPath (Join-Path $Prefix 'lib') -Filter '*boost*.lib' -File | Sort-Object Name)
    foreach($required in @('filesystem','system','regex','date_time')) { if(-not @($boost | Where-Object Name -match "boost_$required").Count) { throw "Missing Boost $required library" } }
    foreach($lib in $boost) { $cmake+='set_property(TARGET UxasDeps::boost APPEND PROPERTY INTERFACE_LINK_LIBRARIES "${_uxas_prefix}/lib/'+$lib.Name+'")' }
    $dir=Join-Path $Prefix 'share/UxasDependencies'
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    [IO.File]::WriteAllLines((Join-Path $dir 'UxasDependenciesConfig.cmake'),$cmake,(New-Object Text.UTF8Encoding($false)))
}

function Invoke-DepsBounded {
    param([string]$File,[string[]]$Arguments,[string]$Directory,[string]$LogRoot,[int]$TimeoutSeconds=60,[switch]$AllowFailure)
    $id=[Guid]::NewGuid().ToString('N')
    $stdout=Join-Path $LogRoot "$id.stdout.log"; $stderr=Join-Path $LogRoot "$id.stderr.log"
    $quoted=@($Arguments | ForEach-Object { if($_ -match '"') { throw 'Embedded quote in process argument.' }; '"'+($_ -replace '(\\+)$','$1$1')+'"' })
    $start=@{FilePath=$File;WorkingDirectory=$Directory;WindowStyle='Hidden';PassThru=$true;RedirectStandardOutput=$stdout;RedirectStandardError=$stderr}
    if($quoted.Count) { $start.ArgumentList=$quoted }
    $record=[ordered]@{file=$File;arguments=$Arguments;workingDirectory=$Directory;started=(Get-Date -Format o);timeoutSeconds=$TimeoutSeconds;timedOut=$false}
    $process=Start-Process @start
    try {
        # Keep the native handle open: PS5.1 Start-Process otherwise may return
        # a Process whose ExitCode is null after a short-lived child exits.
        $null=$process.Handle
        $record.pid=$process.Id
        if(-not $process.WaitForExit($TimeoutSeconds*1000)) { $record.timedOut=$true; $process.Kill(); $process.WaitForExit() }
        $process.Refresh(); $record.exitCode=$process.ExitCode
        $record.output=[IO.File]::ReadAllText($stdout)
        $record.errorOutput=[IO.File]::ReadAllText($stderr)
    } finally { $process.Dispose(); $record.finished=Get-Date -Format o; Write-CppJson $record (Join-Path $LogRoot "$id.command.json") }
    if(($record.timedOut -or $record.exitCode -ne 0) -and -not $AllowFailure) { throw "Dependency probe failed/timed out: $File`n$($record.output)`n$($record.errorOutput)" }
    return [pscustomobject]$record
}
