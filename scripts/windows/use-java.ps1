#requires -Version 5.1
<#
.SYNOPSIS
Validates the locked local tools and activates them in this PowerShell process.
.DESCRIPTION
Run this script in the same PowerShell process as subsequent Java/Ant commands.
Closing that process discards these changes. No registry or persistent PATH is changed.
#>
[CmdletBinding()]
param()

# A child scope prevents helper functions/preferences from leaking when dot-sourced.
& {
    $ErrorActionPreference = 'Stop'
    . (Join-Path $PSScriptRoot 'java-common.ps1')
    $projectRoot = Get-JavaProjectRoot
    $config = Read-JavaToolchain -ProjectRoot $projectRoot
    Set-JavaProcessEnvironment -Config $config -ProjectRoot $projectRoot
    Write-Host "JAVA_HOME=$env:JAVA_HOME"
    Write-Host "ANT_HOME=$env:ANT_HOME"
}

