#requires -Version 5.1
# Run generate-lmcp.ps1 successfully before this repeat/fault integration suite.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable)
$ErrorActionPreference = 'Stop'
$testRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$initial = foreach ($scope in @('Process','User','Machine')) {
    foreach ($name in @('JAVA_HOME','ANT_HOME','PATH','JAVACMD','CLASSPATH','ANT_ARGS','ANT_OPTS',
            'JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','PYTHONPATH','PYTHONHOME')) {
        [pscustomobject]@{scope=$scope;name=$name;value=[Environment]::GetEnvironmentVariable($name,$scope)}
    }
}
$policy = Get-ExecutionPolicy -List | ConvertTo-Json -Compress
& $PythonExecutable -I -B -X utf8 (Join-Path $testRoot 'tests/lmcp/generation_checks.py') --root $testRoot --powershell "$PSHOME/powershell.exe"
if ($LASTEXITCODE -ne 0) { throw 'T03 integration checks failed; see their run directory.' }
foreach ($item in $initial) {
    if ([Environment]::GetEnvironmentVariable($item.name,$item.scope) -cne $item.value) { throw "Environment changed: $($item.scope)/$($item.name)" }
}
if ((Get-ExecutionPolicy -List | ConvertTo-Json -Compress) -cne $policy) { throw 'Execution policy changed.' }
Write-Host 'PASS: 36 process/user/machine environment values and execution policies unchanged.'
