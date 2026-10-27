#requires -Version 7.0
[CmdletBinding()]
param(
    [switch]$Run, [Alias('DryRun')][switch]$Check,
    [ValidateSet('TwoTurn','Session')][string]$Mode = 'TwoTurn',
    [string]$RequestFile, [string]$MaxCostCny = '2.00',
    [ValidateRange(1,10)][int]$ValidMinutes = 10,
    [ValidateRange(1,1800)][int]$RunSeconds = 300, [string]$ReportRoot,
    [ValidateRange(1,5)][int]$MaxTurns = 5, [string]$TotalBudgetCny = '8.02', [string[]]$Members
)
. (Join-Path $PSScriptRoot 'qq_bot_test_common.ps1')
$ErrorActionPreference = 'Stop'
$pushed = $false
$directory = $null
$sessionSummary = [ordered]@{ kind='bounded-session'; status='STOPPED'; automatic_retry=$false; client_display_confirmed=$false }
try {
    if ($Run -and $Check) { Stop-BotWorkflow 'WORKFLOW_MODE_CONFLICT' }
    if ($Mode -eq 'TwoTurn' -and $RunSeconds -gt 600) { Stop-BotWorkflow 'WORKFLOW_TWO_TURN_DURATION_LIMIT' }
    if ($Mode -eq 'TwoTurn' -and ($PSBoundParameters.ContainsKey('MaxTurns') -or
            $PSBoundParameters.ContainsKey('TotalBudgetCny') -or $PSBoundParameters.ContainsKey('Members'))) {
        Stop-BotWorkflow 'WORKFLOW_SESSION_OPTIONS_REQUIRE_SESSION_MODE'
    }
    $root = Get-BotFullPath (Join-Path $PSScriptRoot '../..')
    $python = Join-Path $root '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { Stop-BotWorkflow 'WORKFLOW_PYTHON_MISSING' }
    if (-not $RequestFile) { $RequestFile = Join-Path $root 'outputs/qq-bot/conversation.request.json' }
    $request = Get-BotFullPath $RequestFile
    if (-not (Test-Path -LiteralPath $request -PathType Leaf)) { Stop-BotWorkflow 'WORKFLOW_CONFIG_MISSING' }
    Push-Location -LiteralPath $root; $pushed = $true
    if ($Mode -eq 'Session') {
        if ($PSBoundParameters.ContainsKey('MaxCostCny')) { Stop-BotWorkflow 'WORKFLOW_PER_TURN_COST_NOT_APPLICABLE' }
        if (-not $PSBoundParameters.ContainsKey('RunSeconds')) { $RunSeconds = 1800 }
        $arguments = @('-X','utf8','-B','-m','apps.qq_bot.session_run_trial_cli','--request-file',$request,
            '--max-turns',"$MaxTurns",'--total-budget-cny',$TotalBudgetCny,
            '--valid-minutes',"$ValidMinutes",'--run-seconds',"$RunSeconds")
        foreach ($member in $Members) { $arguments += @('--member',$member) }
        $checked = (Invoke-BotChecked -Python $python -Arguments ($arguments + '--check')).Record
        Write-Host ('配置引用：' + $request + '；数据根：' + $checked.data_root)
        Write-Host ('持续会话：' + $checked.provider + ' / ' + $checked.model + '；实例：' + $checked.instance_id + '；设备：' + $checked.device_id)
        Write-Host ('群摘要：' + $checked.group_ref + '；成员摘要：' + ($checked.member_refs -join ', '))
        Write-Host ('最多 ' + $checked.max_turns + ' Turn / ' + $checked.max_model_requests + ' 请求 / ' + $checked.seconds + ' 秒；总预留 ' + $checked.total_reservation_cny + ' 元；总预算 ' + $checked.total_budget_cny + ' 元')
        Write-Host ('Scope：' + $checked.scope_sha256 + '；candidate准备一致，仍须本次进程的人工批准。')
        if (-not $Run) { Write-Host '离线检查通过；未打开数据库、读取密钥、联网或消费批准。'; exit 0 }
        if (-not $ReportRoot) { $ReportRoot = Join-Path $root 'outputs/qq-bot/test-runs' }
        $directory = New-BotRunDirectory -Root $root -ReportRoot $ReportRoot
        $sessionSummary.status = 'RUNNING'; $sessionSummary['scope_sha256'] = $checked.scope_sha256
        $sessionSummary['result'] = Join-Path $directory 'result.json'
        Write-Host ('本次目录：' + $directory + '；以下仅审批一次，包含Provider/QQ及数据披露，不逐轮询问。')
        & $python @arguments --run --directory $directory --confirm-instance-read --confirm-provider-network --confirm-qq-network --enable-mention-ai
        $nativeExit = $LASTEXITCODE
        if (-not (Test-Path -LiteralPath (Join-Path $directory 'result.json') -PathType Leaf)) { Stop-BotWorkflow 'WORKFLOW_RESULT_MISSING' }
        $report = Read-BotJson (Join-Path $directory 'result.json')
        $sessionSummary.status = Test-BotSessionReport -Report $report -Checked $checked -NativeExit $nativeExit
        foreach ($key in @('code','stop_reason','verified_turns','api_accepted_turns','delivery_unknown_turns','report_saved','ram_cleared')) {
            $sessionSummary[$key] = $report[$key]
        }
        $sessionSummary['quota'] = $report['quota']
        Write-Host ('会话已安全结束；验证通过 ' + $report.verified_turns + ' 轮，API接受 ' + $report.api_accepted_turns + ' 轮；客户端显示请人工确认。')
        Write-Host ('最终报告已核实：' + (Join-Path $directory 'result.json'))
        exit 0
    }
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
    if ($Mode -eq 'Session') { $sessionSummary.status = 'FAILED'; $sessionSummary['code'] = $code }
    Write-Host $code
    exit 1
} finally {
    if ($Mode -eq 'Session' -and $directory) {
        if ($sessionSummary.status -eq 'RUNNING') { $sessionSummary.status = 'INTERRUPTED_REPORT_UNCONFIRMED' }
        try { Write-BotJsonNew (Join-Path $directory 'summary.json') $sessionSummary }
        catch {
            Write-Host 'WORKFLOW_SUMMARY_WRITE_FAILED'
            if ($pushed) { Pop-Location; $pushed = $false }
            exit 1
        }
        Write-Host ('记录目录：' + $directory)
    }
    if ($pushed) { Pop-Location }
}
