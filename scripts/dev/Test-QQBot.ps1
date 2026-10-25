#requires -Version 7.0
[CmdletBinding()]
param(
    [switch]$Run, [Alias('DryRun')][switch]$Check,
    [string]$AccessFile, [string]$MonitoringConfig,
    [ValidateRange(1,600)][int]$RunSeconds = 120, [string]$ReportRoot
)
. (Join-Path $PSScriptRoot 'qq_bot_test_common.ps1')
$code = Invoke-BotTestWorkflow -Kind qq -ProjectRoot ([IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))) @PSBoundParameters
exit $code
