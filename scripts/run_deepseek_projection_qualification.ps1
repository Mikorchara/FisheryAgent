# Qualification preparation only. Without -ConfirmNetwork: dry-run plans + fixed order.
# PREPARED - USER MAY RUN NEXT in the normal user PowerShell.
[CmdletBinding()]
param([switch]$ConfirmNetwork)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'projection_qualification_runner.ps1')
$hashes = @{
    'DEEPSEEK-H2-A' = '3bd3d342315a53afe82a42cdfb715846eb657b4ecf463420dc9b6cb0d3510a72'
    'DEEPSEEK-H2-B' = 'a144baec7d8ed58ef9162342f6f61b2ac83267e3421e0b5db527d94d03db1c0d'
    'DEEPSEEK-H2F' = '05a3a3dc1b12b479858c4ca7e569f70c2f6bb38e56a0c6f2e3e3bdcff8274df9'
    'DEEPSEEK-H5-A' = '33d42c5cdc9148bd5db2dbe7dcf1971c01c6e0c96a6ea1d3f96c6b27d79598c9'
    'DEEPSEEK-H5-B' = '04ab561c4f022dd86a627d6ddb732b8d160c3f1eac5eaf2836f725e852f02f42'
}
Invoke-ProjectionQualificationBatch -ModelKey 'deepseek' -ExpectedHashes $hashes `
    -ProjectRoot (Split-Path -Parent $PSScriptRoot) -ConfirmNetwork:$ConfirmNetwork
