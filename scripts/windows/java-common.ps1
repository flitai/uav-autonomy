#requires -Version 5.1
# Internal helpers shared by the two Java toolchain entry points.
function Get-JavaProjectRoot {
    [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
}

function Get-JavaChildPath {
    param([string]$Parent, [string]$Relative)
    $root = [IO.Path]::GetFullPath($Parent).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    $candidate = [IO.Path]::GetFullPath((Join-Path $Parent $Relative))
    if (-not $candidate.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside its expected directory: $Relative"
    }
    return $candidate
}

function Read-JavaToolchain {
    param([string]$ProjectRoot)
    if (-not [Environment]::Is64BitOperatingSystem -or $env:OS -ne 'Windows_NT') {
        throw 'This toolchain requires Windows x64.'
    }
    $config = Get-Content -LiteralPath (Join-Path $ProjectRoot 'config/windows-java-toolchain.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($config.schemaVersion -ne 1 -or $config.platform -ne 'windows-x64' -or
        @($config.tools).Count -ne 2 -or @($config.tools.id | Sort-Object -Unique).Count -ne 2) {
        throw 'Unsupported Java toolchain manifest.'
    }
    foreach ($tool in $config.tools) {
        if ($tool.id -notin @('jdk', 'ant') -or
            $tool.installDirectory -notmatch '^[A-Za-z0-9][A-Za-z0-9._+-]*$' -or
            $tool.archive -notmatch '^[A-Za-z0-9][A-Za-z0-9._+-]*\.zip$' -or
            ([Uri]$tool.url).Scheme -ne 'https') {
            throw 'Invalid tool identity, path or download URL.'
        }
        $length = switch ($tool.hashAlgorithm) { 'SHA256' {64}; 'SHA512' {128}; default {0} }
        if ($length -eq 0 -or $tool.hash -notmatch "^[a-fA-F0-9]{$length}$" -or @($tool.verifyFiles).Count -eq 0) {
            throw "Invalid checksum configuration for $($tool.id)."
        }
        foreach ($relative in @($tool.verifyFiles) + @($tool.licenseFiles)) {
            $null = Get-JavaChildPath -Parent (Join-Path $ProjectRoot '.tools') -Relative $relative
        }
    }
    return $config
}

function Assert-JavaToolInstallation {
    param($Tool, [string]$Directory)
    $receiptPath = Join-Path $Directory '.uav-toolchain.json'
    if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) {
        throw "Missing installation receipt: $Directory. Run setup-java.ps1; existing unrecognized directories are not overwritten."
    }
    $receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($receipt.id -ne $Tool.id -or $receipt.version -ne $Tool.version -or
        $receipt.archiveHash -ne $Tool.hash -or $receipt.hashAlgorithm -ne $Tool.hashAlgorithm) {
        throw "Installation does not match the locked version: $Directory"
    }
    $expectedFiles = @($Tool.verifyFiles) + @($Tool.licenseFiles)
    if (@($receipt.files).Count -ne $expectedFiles.Count) {
        throw "Installation receipt has an unexpected file list: $Directory"
    }
    foreach ($relative in $expectedFiles) {
        $path = Get-JavaChildPath -Parent $Directory -Relative $relative
        $record = @($receipt.files | Where-Object { $_.path -eq $relative })
        if ($record.Count -ne 1 -or -not (Test-Path -LiteralPath $path -PathType Leaf) -or
            (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $record[0].sha256) {
            throw "Installed file is missing or modified: $path"
        }
    }
}

function Set-JavaProcessEnvironment {
    param($Config, [string]$ProjectRoot)
    # Validate both installations before changing any environment variables.
    foreach ($tool in $Config.tools) {
        $directory = Get-JavaChildPath -Parent (Join-Path $ProjectRoot '.tools') -Relative $tool.installDirectory
        Assert-JavaToolInstallation -Tool $tool -Directory $directory
    }
    $jdk = $Config.tools | Where-Object { $_.id -eq 'jdk' }
    $ant = $Config.tools | Where-Object { $_.id -eq 'ant' }
    $env:JAVA_HOME = Join-Path $ProjectRoot ".tools/$($jdk.installDirectory)"
    $env:ANT_HOME = Join-Path $ProjectRoot ".tools/$($ant.installDirectory)"
    $env:JAVACMD = Join-Path $env:JAVA_HOME 'bin/java.exe'
    $env:CLASSPATH = $null
    $bins = @((Join-Path $env:JAVA_HOME 'bin'), (Join-Path $env:ANT_HOME 'bin'))
    $remaining = @($env:PATH -split ';' | Where-Object { $_ -and $_ -notin $bins })
    $env:PATH = (@($bins) + $remaining) -join ';'
}

function Invoke-JavaToolCheck {
    param([string]$File, [string[]]$Arguments)
    # Windows PowerShell 5.1 exposes native stderr (including java -version)
    # as ErrorRecord objects. Capture it without treating it as a failed command.
    $savedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $lines = @(& $File @Arguments 2>&1)
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedPreference
    }
    $output = ($lines | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
    Write-Host "$File $($Arguments -join ' ')"
    Write-Host $output
    Write-Host "Exit code: $code"
    if ($code -ne 0) { throw "Tool failed with exit code $($code): $File" }
    [pscustomobject]@{ file=$File; arguments=$Arguments; exitCode=$code; output=$output }
}

