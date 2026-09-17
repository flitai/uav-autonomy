#requires -Version 5.1
function Invoke-AmaseTcpEntry {
    param([string]$PythonExecutable, [string[]]$EntryArguments)
    $ErrorActionPreference = 'Stop'
    $projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
    $savedLocation = Get-Location
    $savedEncoding = [Console]::OutputEncoding
    $before = foreach ($scope in @('Process','User','Machine')) {
        foreach ($name in @('JAVA_HOME','ANT_HOME','PATH','JAVACMD','CLASSPATH','ANT_ARGS','ANT_OPTS',
                'JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','PYTHONPATH','PYTHONHOME')) {
            [pscustomobject]@{scope=$scope;name=$name;value=[Environment]::GetEnvironmentVariable($name,$scope)}
        }
    }
    $policy = Get-ExecutionPolicy -List | ConvertTo-Json -Compress
    try {
        if (-not $PythonExecutable) { $PythonExecutable = (Get-Command python.exe -ErrorAction Stop).Source }
        $pythonPath = (Resolve-Path -LiteralPath $PythonExecutable -ErrorAction Stop).Path
        [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
        & $pythonPath -I -B -X utf8 (Join-Path $projectRoot 'scripts/validation/amase_tcp.py') --root $projectRoot @EntryArguments
        if ($LASTEXITCODE -ne 0) { throw "AMASE TCP operation failed (exit $LASTEXITCODE); see its run record." }
    } finally {
        [Console]::OutputEncoding = $savedEncoding
        Set-Location -LiteralPath $savedLocation.Path
        foreach ($item in $before) {
            if ([Environment]::GetEnvironmentVariable($item.name,$item.scope) -cne $item.value) {
                throw "Environment changed: $($item.scope)/$($item.name)"
            }
        }
        if ((Get-ExecutionPolicy -List | ConvertTo-Json -Compress) -cne $policy) { throw 'Execution policy changed.' }
    }
    Write-Host 'PASS: 36 environment values and execution policies unchanged.'
}
