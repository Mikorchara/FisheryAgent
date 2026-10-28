#requires -Version 7.0
[CmdletBinding()]
param(
    [switch]$Run, [Alias('DryRun')][switch]$Check,
    [Parameter(Mandatory)][string]$RequestFile,
    [Parameter(Mandatory)][string]$InstanceRoot,
    [string]$InstanceId = 'bot2c-isolated', [string]$DeviceId = 'sim-pond-1',
    [ValidateSet('A','B','C','D','E')][string[]]$Category,
    [string[]]$CaseId, [ValidateRange(1,5)][int]$Repeat = 1,
    [string]$TotalBudgetCny,
    [ValidateRange(1,1800)][int]$RunSeconds = 1800,
    [ValidateRange(1,86400)][int]$ExperimentSeconds = 7200,
    [string]$Suite, [string]$ReportRoot, [switch]$SaveRaw
)
$ErrorActionPreference = 'Stop'
$pushed = $false
try {
    if ($Run -and $Check) { throw 'RESEARCH_MODE_CONFLICT' }
    $root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
    $python = Join-Path $root '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'RESEARCH_PYTHON_MISSING' }
    if (-not (Test-Path -LiteralPath $RequestFile -PathType Leaf)) { throw 'RESEARCH_REQUEST_MISSING' }
    $arguments = @('-X','utf8','-B','-m','apps.qq_bot.hybrid_research_cli',
        '--request-file',([IO.Path]::GetFullPath($RequestFile)),
        '--instance-root',([IO.Path]::GetFullPath($InstanceRoot)),
        '--instance-id',$InstanceId,'--device-id',$DeviceId,'--repeat',"$Repeat",
        '--run-seconds',"$RunSeconds",'--experiment-seconds',"$ExperimentSeconds")
    if ($TotalBudgetCny) { $arguments += @('--total-budget-cny',$TotalBudgetCny) }
    foreach ($item in $Category) { $arguments += @('--category',$item) }
    foreach ($item in $CaseId) { $arguments += @('--case-id',$item) }
    if ($Suite) { $arguments += @('--suite',([IO.Path]::GetFullPath($Suite))) }
    if ($ReportRoot) { $arguments += @('--report-root',([IO.Path]::GetFullPath($ReportRoot))) }
    if ($SaveRaw) { $arguments += '--save-raw' }
    Push-Location -LiteralPath $root; $pushed = $true
    if ($Run) {
        if (-not $TotalBudgetCny) { throw 'EXPERIMENT_EXPLICIT_TOTAL_BUDGET_REQUIRED' }
        Write-Host '仅本地Qwen实验，不连接QQ。下一步显示完整计划并等待人工审批，Ctrl+C停止。'
        & $python @arguments --run --confirm-provider-network --confirm-instance-read
    } else {
        & $python @arguments --check
        if ($LASTEXITCODE -eq 0) { Write-Host '离线检查通过；未打开Monitoring、读取密钥或联网，未创建批准。' }
    }
    $code = $LASTEXITCODE
    exit $code
} catch {
    $code = $_.Exception.Message
    if ($code -cnotmatch '^[A-Z0-9_]{1,80}$') { $code = 'RESEARCH_WORKFLOW_FAILED' }
    Write-Host $code
    exit 1
} finally {
    if ($pushed) { Pop-Location }
}
