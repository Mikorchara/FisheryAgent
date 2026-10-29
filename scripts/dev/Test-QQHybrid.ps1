#requires -Version 7.0
[CmdletBinding()]
param(
    [switch]$Run, [Alias('DryRun')][switch]$Check,
    [string]$RequestFile, [ValidateRange(1,5)][int]$MaxTurns = 5,
    [ValidateRange(1,1800)][int]$RunSeconds = 1800,
    [string]$TotalBudgetCny = '8.02', [string[]]$Members,
    [ValidateRange(1,10)][int]$ValidMinutes = 10, [string]$ReportRoot
)
. (Join-Path $PSScriptRoot 'qq_bot_test_common.ps1')
$ErrorActionPreference = 'Stop'
$directory = $null
$pushed = $false
$summary = [ordered]@{kind='experimental-qq-hybrid';status='STOPPED';automatic_retry=$false;client_display_confirmed=$false}
try {
    if ($Run -and $Check) { Stop-BotWorkflow 'WORKFLOW_MODE_CONFLICT' }
    $root = Get-BotFullPath (Join-Path $PSScriptRoot '../..')
    $python = Join-Path $root '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { Stop-BotWorkflow 'WORKFLOW_PYTHON_MISSING' }
    if (-not $RequestFile) { $RequestFile = Join-Path $root 'outputs/qq-bot/conversation.request.json' }
    $request = Get-BotFullPath $RequestFile
    if (-not (Test-Path -LiteralPath $request -PathType Leaf)) { Stop-BotWorkflow 'WORKFLOW_CONFIG_MISSING' }
    Push-Location -LiteralPath $root; $pushed = $true
    $arguments = @('-X','utf8','-B','-m','apps.qq_bot.hybrid_trial_cli','--request-file',$request,
        '--max-turns',"$MaxTurns",'--run-seconds',"$RunSeconds",'--total-budget-cny',$TotalBudgetCny,
        '--valid-minutes',"$ValidMinutes")
    foreach ($member in $Members) { $arguments += @('--member',$member) }
    $checked = (Invoke-BotChecked -Python $python -Arguments ($arguments + '--check')).Record
    Write-Host ('Hybrid实验：' + $checked.provider + ' / ' + $checked.model + '；实例 ' + $checked.instance_id + ' / ' + $checked.device_id)
    Write-Host ('数据根：' + $checked.data_root + '；群摘要 ' + $checked.group_ref + '；成员摘要 ' + ($checked.member_refs -join ', '))
    Write-Host ('Scope：' + $checked.scope_sha256 + '；最多 ' + $checked.max_turns + ' Turn / ' + $checked.max_model_requests + ' 请求 / ' + $checked.seconds + ' 秒')
    Write-Host ('预算 ' + $checked.total_budget_cny + ' 元；保守预留 ' + $checked.total_reservation_cny + ' 元；不是云平台账单硬上限。')
    Write-Host $checked.residual_risk
    if (-not $Run) { Write-Host '离线检查通过；未打开数据库、读取密钥、联网或消费批准。'; exit 0 }
    if (-not $ReportRoot) { $ReportRoot = Join-Path $root 'outputs/qq-bot/test-runs' }
    $directory = New-BotRunDirectory -Root $root -ReportRoot $ReportRoot
    $summary.status = 'RUNNING'; $summary['scope_sha256'] = $checked.scope_sha256
    $summary['result'] = Join-Path $directory 'result.json'
    Write-Host ('本次记录：' + $directory + '；接下来由你一次审批Provider、QQ和实验性General发布；Enter取消，Ctrl+C停止。')
    & $python @arguments --run --directory $directory --confirm-instance-read --confirm-provider-network --confirm-qq-network --enable-mention-ai --confirm-general-experimental
    $nativeExit = $LASTEXITCODE
    if (-not (Test-Path -LiteralPath $summary.result -PathType Leaf)) { Stop-BotWorkflow 'WORKFLOW_RESULT_MISSING' }
    $report = Read-BotJson $summary.result
    if ($report.contract -cne $checked.contract) { Stop-BotWorkflow 'WORKFLOW_RESULT_MISMATCH' }
    $summary.status = Test-BotSessionReport -Report $report -Checked $checked -NativeExit $nativeExit -ExpectedContract 'qq-qwen-hybrid-experimental-run@1'
    foreach ($key in @('code','stop_reason','verified_turns','api_accepted_turns','delivery_unknown_turns','report_saved','ram_cleared','quota')) { $summary[$key] = $report[$key] }
    Write-Host ('已结束；合同验证通过 ' + $report.verified_turns + ' 轮，QQ API接受 ' + $report.api_accepted_turns + ' 轮；客户端显示须人工确认。')
    Write-Host ('最终报告已核实：' + $summary.result)
    exit 0
} catch {
    $code = $_.Exception.Message
    if ($code -cnotmatch '^[A-Z0-9_]{1,80}$') { $code = 'WORKFLOW_FAILED' }
    $summary.status = 'FAILED'; $summary['code'] = $code
    Write-Host $code
    exit 1
} finally {
    if ($directory) {
        if ($summary.status -eq 'RUNNING') { $summary.status = 'INTERRUPTED_REPORT_UNCONFIRMED' }
        try { Write-BotJsonNew (Join-Path $directory 'summary.json') $summary }
        catch { Write-Host 'WORKFLOW_SUMMARY_WRITE_FAILED'; if ($pushed) { Pop-Location; $pushed = $false }; exit 1 }
        Write-Host ('记录目录：' + $directory)
    }
    if ($pushed) { Pop-Location }
}
