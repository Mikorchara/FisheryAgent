#requires -Version 7.0
[CmdletBinding()]
param(
    [switch]$Run, [Alias('DryRun')][switch]$Check,
    [string]$RequestFile, [string]$MaxCostCny = '2.00',
    [ValidateRange(1,10)][int]$ValidMinutes = 10,
    [ValidateRange(1,600)][int]$RunSeconds = 300, [string]$ReportRoot
)
. (Join-Path $PSScriptRoot 'qq_bot_test_common.ps1')
$ErrorActionPreference = 'Stop'
$pushed = $false
try {
    if ($Run -and $Check) { Stop-BotWorkflow 'WORKFLOW_MODE_CONFLICT' }
    $root = Get-BotFullPath (Join-Path $PSScriptRoot '../..')
    $python = Join-Path $root '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { Stop-BotWorkflow 'WORKFLOW_PYTHON_MISSING' }
    if (-not $RequestFile) { $RequestFile = Join-Path $root 'outputs/qq-bot/conversation.request.json' }
    $request = Get-BotFullPath $RequestFile
    if (-not (Test-Path -LiteralPath $request -PathType Leaf)) { Stop-BotWorkflow 'WORKFLOW_CONFIG_MISSING' }
    Push-Location -LiteralPath $root; $pushed = $true
    $arguments = @('-X','utf8','-B','-m','apps.qq_bot.conversation_trial_cli','--request-file',$request,
        '--max-cost-cny',$MaxCostCny,'--valid-minutes',"$ValidMinutes",'--run-seconds',"$RunSeconds")
    # Check does not connect Monitoring or resolve credentials, and creates no approval.
    $checked = (Invoke-BotChecked -Python $python -Arguments ($arguments + '--check')).Record
    Write-Host ('模型：' + $checked.model + '；实例：' + $checked.instance_id + '；设备：' + $checked.device_id)
    Write-Host ('群摘要：' + $checked.group_ref + '；成员摘要：' + $checked.member_ref)
    Write-Host ('每轮费用上限：' + $checked.cost_cap_per_turn_cny + ' 元；两轮总上限：' + $checked.total_cost_cap_cny + ' 元；Scope：' + $checked.scope_sha256)
    if (-not $Run) { Write-Host '离线配置与合同检查通过；未打开数据库、读取密钥或联网。'; exit 0 }
    Confirm-BotNetwork 'QWEN' '允许指定Qwen模型逐轮试用；每轮仍须在终端独立审批'
    Confirm-BotNetwork 'QQ' '允许指定QQ测试群及成员接收模拟数据与受限解释'
    if (-not $ReportRoot) { $ReportRoot = Join-Path $root 'outputs/qq-bot/test-runs' }
    $directory = New-BotRunDirectory -Root $root -ReportRoot $ReportRoot
    Write-Host ('本次计划、批准和结果目录：' + $directory)
    Write-Host '请在每轮批准后再向机器人发送问题；第二轮计划依照第一轮实际成功历史生成。Ctrl+C停止。'
    # Keep a real console for the interruptible second approval, not a blocking pipe/input worker.
    & $python @arguments --run --directory $directory --confirm-instance-read --confirm-provider-network --confirm-qq-network --enable-mention-ai
    $code = $LASTEXITCODE
    Write-Host ('最终报告：' + (Join-Path $directory 'result.json'))
    exit $code
} catch {
    $code = $_.Exception.Message
    if ($code -cnotmatch '^[A-Z0-9_]{1,80}$') { $code = 'WORKFLOW_FAILED' }
    Write-Host $code
    exit 1
} finally { if ($pushed) { Pop-Location } }
