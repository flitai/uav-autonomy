[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExecutable,
      [Parameter(Mandatory=$true)][string]$BaselineRunId,
      [Parameter(Mandatory=$true)][string]$CoverageBuildRunId,
      [Parameter(Mandatory=$true)][string]$FullRunId,
      [Parameter(Mandatory=$true)][string]$ScaleRunId,
      [Parameter(Mandatory=$true)][string]$StageBuildRunId)
& (Join-Path $PSScriptRoot '../../scripts/windows/cesium-stage.ps1') -Action Qualify `
    -PythonExecutable $PythonExecutable -BaselineRunId $BaselineRunId `
    -CoverageBuildRunId $CoverageBuildRunId -FullRunId $FullRunId `
    -ScaleRunId $ScaleRunId -StageBuildRunId $StageBuildRunId
if ($LASTEXITCODE -ne 0) {exit $LASTEXITCODE}
