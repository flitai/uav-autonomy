#requires -Version 5.1
<# .SYNOPSIS
Validates and activates the locked C++ tools in this process. Close it to deactivate.
#>
[CmdletBinding()]
param()
& {
    $ErrorActionPreference = 'Stop'
    . (Join-Path $PSScriptRoot 'cpp-common.ps1')
    $config = Read-CppConfig
    $before = Get-CppEnvironment
    try {
        $tools = Set-CppProcessEnvironment $config
        $null = Test-CppToolVersions $config $tools $script:CppProjectRoot
        Write-Host "MSVC=$($tools.system.vcDirectory)"
        Write-Host "SDK=$($tools.system.sdkDirectory) $($tools.system.sdkKitVersion)"
        Write-Host "CMake=$($tools.cmake)"
        Write-Host "Ninja=$($tools.ninja)"
        Write-Host "vcpkg=$($tools.vcpkg)"
    } catch { Restore-CppEnvironment $before; throw }
}
