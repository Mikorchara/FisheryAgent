#requires -Version 7.0
[CmdletBinding()]
param(
    [switch]$Run, [Alias('DryRun')][switch]$Check,
    [string]$AccessFile, [string]$MonitoringConfig, [string]$AIConfig, [string]$PolicyDirectory,
    [string]$GroupId, [string]$MemberId, [string]$MaxCostCny = '2.00',
    [ValidateRange(1,30)][int]$ValidMinutes = 10, [string]$ReportRoot
)
. (Join-Path $PSScriptRoot 'qq_bot_test_common.ps1')
$code = Invoke-BotTestWorkflow -Kind provider -ProjectRoot ([IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))) @PSBoundParameters
exit $code
