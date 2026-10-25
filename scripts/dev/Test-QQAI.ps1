#requires -Version 7.0
[CmdletBinding()]
param(
    [switch]$Run, [Alias('DryRun')][switch]$Check,
    [string]$AccessFile, [string]$MonitoringConfig, [string]$AIConfig, [string]$PolicyDirectory,
    [string]$ProviderReport, [string]$GroupId, [string]$MemberId, [string]$MaxCostCny = '2.00',
    [ValidateRange(1,30)][int]$ValidMinutes = 10,
    [ValidateRange(1,600)][int]$RunSeconds = 120, [string]$ReportRoot
)
. (Join-Path $PSScriptRoot 'qq_bot_test_common.ps1')
$code = Invoke-BotTestWorkflow -Kind qqai -ProjectRoot ([IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))) @PSBoundParameters
exit $code
