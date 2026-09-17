#requires -Version 5.1
<#
.SYNOPSIS
Generates and validates the unified LMCP libraries using existing locked tools.
.PARAMETER PythonExecutable
Full path to the previously verified Python 3.14.7 x64 interpreter. No installation is performed.
#>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'java-common.ps1')
$projectRoot = Get-JavaProjectRoot
$savedLocation = Get-Location
$savedEncoding = [Console]::OutputEncoding
$names = @('JAVA_HOME','ANT_HOME','PATH','JAVACMD','CLASSPATH','ANT_ARGS','ANT_OPTS',
    'JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','PYTHONPATH','PYTHONHOME')
$saved = @{}
foreach ($name in $names) { $saved[$name] = [Environment]::GetEnvironmentVariable($name,'Process') }
try {
    if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) { throw 'PythonExecutable must identify an existing interpreter.' }
    $pythonPath = (Resolve-Path -LiteralPath $PythonExecutable).Path
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    foreach ($name in @('ANT_ARGS','ANT_OPTS','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','PYTHONPATH','PYTHONHOME')) {
        [Environment]::SetEnvironmentVariable($name,$null,'Process')
    }
    & (Join-Path $PSScriptRoot 'use-java.ps1')
    Set-Location -LiteralPath $projectRoot
    & $pythonPath -I -B -X utf8 (Join-Path $projectRoot 'scripts/lmcp/generate.py') --root $projectRoot
    if ($LASTEXITCODE -ne 0) { throw "LMCP generation/validation failed with exit code $LASTEXITCODE. See the reported run directory." }
} finally {
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name,$saved[$name],'Process') }
    [Console]::OutputEncoding = $savedEncoding
    Set-Location -LiteralPath $savedLocation.Path
}
