#requires -Version 5.1
function Invoke-AmaseEntry {
    param([string]$PythonExecutable, [string[]]$EntryArguments)
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
        if (-not $PythonExecutable) { $PythonExecutable = (Get-Command python.exe -ErrorAction Stop).Source }
        if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) { throw 'Specify an existing PythonExecutable.' }
        $pythonPath = (Resolve-Path -LiteralPath $PythonExecutable).Path
        [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
        foreach ($name in @('ANT_ARGS','ANT_OPTS','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','PYTHONPATH','PYTHONHOME')) {
            [Environment]::SetEnvironmentVariable($name,$null,'Process')
        }
        & (Join-Path $PSScriptRoot 'use-java.ps1')
        & $pythonPath -I -B -X utf8 (Join-Path $projectRoot 'scripts/amase/amase.py') --root $projectRoot @EntryArguments
        if ($LASTEXITCODE -ne 0) { throw "AMASE operation failed (exit $LASTEXITCODE); see its run record." }
    } finally {
        foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name,$saved[$name],'Process') }
        [Console]::OutputEncoding = $savedEncoding
        Set-Location -LiteralPath $savedLocation.Path
    }
}
