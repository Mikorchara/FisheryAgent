#requires -Version 7.0
# Thin operator workflow only. Approval, scope, cost and execution stay in Python.
Set-StrictMode -Version Latest

function Stop-BotWorkflow([string]$Code) { throw [InvalidOperationException]::new($Code) }

function Get-BotFullPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { Stop-BotWorkflow 'WORKFLOW_PATH_REQUIRED' }
    $full = [IO.Path]::GetFullPath($Path)
    if ($full.StartsWith('\\') -or ([IO.DriveInfo]::new([IO.Path]::GetPathRoot($full))).DriveType -ne 'Fixed') {
        Stop-BotWorkflow 'WORKFLOW_LOCAL_DISK_REQUIRED'
    }
    $cursor = $full
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -LiteralPath $cursor -Force -ErrorAction Stop).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                Stop-BotWorkflow 'WORKFLOW_REPARSE_POINT_REJECTED'
            }
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    return $full
}

function Read-BotJson([string]$Path) {
    $full = Get-BotFullPath $Path
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { Stop-BotWorkflow 'WORKFLOW_CONFIG_MISSING' }
    if ((Get-Item -LiteralPath $full).Length -gt 65536) { Stop-BotWorkflow 'WORKFLOW_JSON_TOO_LARGE' }
    try { return [IO.File]::ReadAllText($full) | ConvertFrom-Json -AsHashtable -ErrorAction Stop }
    catch { Stop-BotWorkflow 'WORKFLOW_INVALID_JSON' }
}

function Write-BotJsonNew([string]$Path, $Value) {
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($Value | ConvertTo-Json -Depth 12) + "`n")
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
}

function Get-BotTag([string]$Value) {
    $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
    return ([Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes))).Substring(0, 12).ToLowerInvariant()
}

function New-BotRunDirectory([string]$Root, [string]$ReportRoot) {
    $outputs = (Get-BotFullPath (Join-Path $Root 'outputs')).TrimEnd('\') + '\'
    $base = Get-BotFullPath $ReportRoot
    if (-not $base.StartsWith($outputs, [StringComparison]::OrdinalIgnoreCase)) {
        Stop-BotWorkflow 'WORKFLOW_REPORT_MUST_BE_IN_PROJECT_OUTPUTS'
    }
    [void][IO.Directory]::CreateDirectory($base)
    $name = 'test-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [Guid]::NewGuid().ToString('N')
    $directory = Join-Path $base $name
    # New-Item without Force refuses existing names; never reuse an approval/run directory.
    [void](New-Item -ItemType Directory -Path $directory -ErrorAction Stop)
    return $directory
}

function Invoke-BotNative([string]$Python, [string[]]$Arguments, [switch]$ApprovalPrompt) {
    # Keep stdin attached to the user's console. Never pipe APPROVE into Python.
    # Consume bounded output in memory; neither raw stdout nor stderr is logged.
    $last = $null; $codes = [Collections.Generic.List[string]]::new(); $total = 0
    $oldPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $Python @Arguments 2>&1 | ForEach-Object {
            $line = $_.ToString(); $total += $line.Length
            if ($line.Length -gt 65536 -or $total -gt 1048576) { Stop-BotWorkflow 'WORKFLOW_OUTPUT_LIMIT' }
            if ($ApprovalPrompt -and $line -match 'APPROVE [a-f0-9]{12}') {
                Write-Host ('请在此输入审批挑战：' + $Matches[0])
            }
            try {
                $item = $line | ConvertFrom-Json -AsHashtable -ErrorAction Stop
                if ($item -is [System.Collections.IDictionary] -and $item['code'] -cmatch '^[A-Z0-9_]{1,80}$') {
                    $last = $item
                    if ($codes.Count -ge 2048) { Stop-BotWorkflow 'WORKFLOW_OUTPUT_LIMIT' }
                    $codes.Add([string]$item['code'])
                    switch -CaseSensitive ($item['code']) {
                        'QQ_GATEWAY_READY' { Write-Host 'QQ 已连接；等待授权成员的测试消息。' }
                        'QQ_REPLY_ACCEPTED' { Write-Host 'QQ API 已接受回复；请在客户端确认显示。' }
                        'QQ_STOPPED' { Write-Host 'QQ 会话已停止。' }
                    }
                }
            } catch {
                if ($_.Exception.Message -eq 'WORKFLOW_OUTPUT_LIMIT') { throw }
                # Non-JSON native diagnostics are deliberately suppressed.
            }
        }
        $exitCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $oldPreference }
    if ($null -eq $last) { Stop-BotWorkflow 'WORKFLOW_NATIVE_NO_STATUS' }
    return @{ ExitCode = $exitCode; Record = $last; Codes = $codes.ToArray() }
}

function Invoke-BotChecked([string]$Python, [string[]]$Arguments, [switch]$ApprovalPrompt) {
    $result = Invoke-BotNative -Python $Python -Arguments $Arguments -ApprovalPrompt:$ApprovalPrompt
    if ($result.ExitCode -ne 0) { Stop-BotWorkflow ([string]$result.Record['code']) }
    return $result
}

function Confirm-BotNetwork([string]$Word, [string]$Description) {
    if ((Read-Host ($Description + '；继续请输入 ' + $Word)) -cne $Word) {
        Stop-BotWorkflow 'WORKFLOW_OPERATOR_CANCELLED'
    }
}

function Invoke-BotTestWorkflow {
    param(
        [Parameter(Mandatory)][ValidateSet('qq', 'provider', 'qqai')][string]$Kind,
        [Parameter(Mandatory)][string]$ProjectRoot,
        [switch]$Run, [Alias('DryRun')][switch]$Check,
        [string]$AccessFile, [string]$MonitoringConfig, [string]$AIConfig,
        [string]$PolicyDirectory, [string]$ProviderReport, [string]$GroupId, [string]$MemberId,
        [string]$MaxCostCny = '2.00', [ValidateRange(1,30)][int]$ValidMinutes = 10,
        [ValidateRange(1,600)][int]$RunSeconds = 120, [string]$ReportRoot
    )
    $ErrorActionPreference = 'Stop'
    $summary = [ordered]@{ schema_version = 1; kind = $Kind; mode = 'CHECK'; status = 'STOPPED'
        network_authorized = $false; automatic_retry = $false; client_display_confirmed = $false }
    $directory = $null; $pushed = $false; $exitCode = 1
    try {
        if ($Run -and $Check) { Stop-BotWorkflow 'WORKFLOW_MODE_CONFLICT' }
        if ($Run) { $summary.mode = 'RUN' }
        $root = Get-BotFullPath $ProjectRoot
        Push-Location -LiteralPath $root; $pushed = $true
        $python = Join-Path $root '.venv/Scripts/python.exe'
        if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { Stop-BotWorkflow 'WORKFLOW_PYTHON_MISSING' }
        if (-not $AccessFile) { $AccessFile = Join-Path $root 'outputs/qq-bot/access.json' }
        if (-not $MonitoringConfig) { $MonitoringConfig = Join-Path $root 'outputs/qq-bot/monitoring.bot2c.json' }
        $AccessFile = Get-BotFullPath $AccessFile; $MonitoringConfig = Get-BotFullPath $MonitoringConfig
        [void](Read-BotJson $AccessFile); [void](Read-BotJson $MonitoringConfig)
        $baseArgs = @('-X', 'utf8', '-B', '-m', 'apps.qq_bot')
        $fixedArgs = @('--access-file', $AccessFile, '--monitoring-config', $MonitoringConfig)
        [void](Invoke-BotChecked $python ($baseArgs + '--check-config' + $fixedArgs))
        [void](Invoke-BotChecked $python ($baseArgs + '--check-monitoring' + $fixedArgs))
        if (-not $ReportRoot) { $ReportRoot = Join-Path $root 'outputs/qq-bot/test-runs' }
        if ($Kind -ne 'qq') {
            if (-not $AIConfig) { $AIConfig = Join-Path $root 'outputs/qq-bot/ai.qwen-fast.provider.json' }
            if (-not $PolicyDirectory) { $PolicyDirectory = Join-Path $root 'outputs/tool-policies' }
            $AIConfig = Get-BotFullPath $AIConfig; $PolicyDirectory = Get-BotFullPath $PolicyDirectory
            $ai = Read-BotJson $AIConfig
            # Selection only; Python remains the authority for authorization/intersection.
            $pairs = @(
                foreach ($grant in $ai['grants']) {
                    foreach ($member in $grant['members']) {
                        if ((-not $GroupId -or $GroupId -ceq $grant['group_id']) -and
                            (-not $MemberId -or $MemberId -ceq $member)) {
                            @{ Group = $grant['group_id']; Member = $member }
                        }
                    }
                }
            )
            if ($pairs.Count -ne 1) { Stop-BotWorkflow 'WORKFLOW_EXPLICIT_GROUP_MEMBER_REQUIRED' }
            $GroupId = $pairs[0].Group; $MemberId = $pairs[0].Member
            if ($Kind -eq 'qqai') {
                if (-not $ProviderReport) { Stop-BotWorkflow 'TRIAL_PROVIDER_PREREQUISITE_REQUIRED' }
                $ProviderReport = Get-BotFullPath $ProviderReport
                [void](Read-BotJson $ProviderReport)
            } elseif ($ProviderReport) { Stop-BotWorkflow 'WORKFLOW_PROVIDER_REPORT_NOT_APPLICABLE' }
        }
        $directory = New-BotRunDirectory $root $ReportRoot
        $summary['directory'] = $directory
        if ($Kind -eq 'qq') {
            if ($Run) {
                Confirm-BotNetwork 'QQ' '将连接 QQ，读取上述明确指定实例；固定命令不调用模型'
                $summary.network_authorized = $true
                Write-Host 'QQ 固定命令测试中；在授权群中 @机器人 help / 当前水质 / 异常。Ctrl+C 停止。'
                $connected = Invoke-BotChecked $python ($baseArgs + '--connect' + $fixedArgs +
                    @('--confirm-qq-network', '--run-seconds', [string]$RunSeconds))
                $summary['reply_api_acceptances'] = @($connected.Codes | Where-Object { $_ -ceq 'QQ_REPLY_ACCEPTED' }).Count
                $summary.status = 'SESSION_ENDED_CHECK_CLIENT'
            } else { $summary.status = 'CHECK_PASSED_NO_NETWORK' }
        } else {
            $trialArgs = @('-X', 'utf8', '-B', '-m', 'apps.qq_bot.trial')
            $phase = if ($Kind -eq 'provider') { 'provider' } else { 'qq' }
            $planPath = Join-Path $directory 'plan.json'
            $approvalPath = Join-Path $directory 'approval.json'
            $resultPath = Join-Path $directory 'result.json'
            $prepare = $trialArgs + @('--prepare', '--phase', $phase, '--access-file', $AccessFile,
                '--monitoring-config', $MonitoringConfig, '--ai-config', $AIConfig,
                '--policy-directory', $PolicyDirectory, '--group-id', $GroupId, '--member-id', $MemberId,
                '--max-cost-cny', $MaxCostCny, '--valid-minutes', [string]$ValidMinutes,
                '--output', $planPath, '--confirm-instance-read')
            if ($Kind -eq 'qqai') { $prepare += @('--provider-receipt', $ProviderReport) }
            [void](Invoke-BotChecked $python $prepare)
            $plan = Read-BotJson $planPath
            $summary['plan'] = $planPath; $summary['scope_sha256'] = $plan['scope_sha256']
            $summary['instance_id'] = $plan['instance_id']; $summary['device_id'] = $plan['device_id']
            $summary['expires_at'] = $plan['expires_at']; $summary['group_tag'] = Get-BotTag $GroupId
            $summary['member_tag'] = Get-BotTag $MemberId
            $summary['max_cost_cny'] = $plan['max_cost_cny']
            $summary['reservation_cny'] = $plan['scope']['cost']['reservation_cny']
            $summary['preset_id'] = $plan['scope']['base_scope']['runtime']['preset_id']
            $summary['model'] = $plan['scope']['base_scope']['runtime']['identity'][3]
            Write-Host ('Preset {0} / 模型 {1}；SIMULATOR；实例 {2} / 设备 {3}' -f $summary.preset_id, $summary.model, $plan['instance_id'], $plan['device_id'])
            Write-Host ('群/成员摘要 {0}/{1}；有效至 {2}' -f $summary.group_tag, $summary.member_tag, $summary.expires_at)
            Write-Host ('1 Turn / 最多 2 模型请求 / 每次输出 512 tokens / 90s；费用上限 {0} CNY，预留 {1} CNY' -f $summary.max_cost_cny, $summary.reservation_cny)
            Write-Host '模型自由文本不展示；SDK 线程无法保证强制退出，远端计算/计费是否停止未知。'
            if (-not $Run) { $summary.status = 'PLAN_READY_NO_APPROVAL_NO_NETWORK' }
            else {
                Confirm-BotNetwork 'QWEN' '批准本次真实 Qwen 网络请求及模拟观测数据披露（仍须下一步逐项审批）'
                if ($Kind -eq 'qqai') { Confirm-BotNetwork 'QQ' '另行批准连接测试群并披露来源摘要' }
                $summary.network_authorized = $true
                Write-Host ('计划文件仅供本机审阅：' + $planPath)
                Write-Host '审批涵盖模型、实例、设备、群成员、有效期、费用及上述剩余风险；不接受请中止。'
                $approved = Invoke-BotChecked $python ($trialArgs + @('--approve', '--plan', $planPath,
                    '--output', $approvalPath, '--confirm-instance-read')) -ApprovalPrompt
                $digest = [string]$approved.Record['approval_sha256']
                if ($digest -cnotmatch '^[a-f0-9]{64}$') { Stop-BotWorkflow 'WORKFLOW_APPROVAL_DIGEST_MISSING' }
                $approvedArgs = @('--approval', $approvalPath, '--approval-sha256', $digest, '--confirm-instance-read')
                [void](Invoke-BotChecked $python ($trialArgs + '--check' + $approvedArgs))
                $summary['approval'] = $approvalPath; $summary['result'] = $resultPath
                $execute = $trialArgs + @('--run-' + $phase) + $approvedArgs +
                    @('--output', $resultPath, '--confirm-provider-network')
                if ($Kind -eq 'qqai') { $execute += @('--confirm-qq-network', '--run-seconds', [string]$RunSeconds) }
                $ran = Invoke-BotNative $python $execute
                $report = $ran.Record
                # Strict allowlist: do not copy arbitrary report/model/message fields.
                $summary['model_requests'] = $report['model_requests']
                $summary['model_text_displayed'] = $report['model_text_displayed']
                if ($report['usage']) {
                    $summary['usage'] = @{ input_tokens = $report['usage']['input_tokens']; output_tokens = $report['usage']['output_tokens'] }
                }
                if ($report['sdk_resources']) {
                    $r = $report['sdk_resources']
                    $summary['sdk_resources'] = @{ state = $r['state']; thread_exited = $r['thread_exited']; local_io_closed = $r['local_io_closed']; cleanup_error = $r['cleanup_error'] }
                }
                $summary['api_accepted'] = $false
                if ($Kind -eq 'qqai') {
                    $summary.api_accepted = @($report['delivery'] | Where-Object { $_['state'] -ceq 'DELIVERED' -and $_['api_accepted'] -eq $true }).Count -gt 0
                }
                if ($ran.ExitCode -ne 0) { Stop-BotWorkflow ([string]$report['code']) }
                if ($report['completed'] -ne $true) { Stop-BotWorkflow 'WORKFLOW_NOT_COMPLETED_NO_RETRY' }
                $summary.status = if ($Kind -eq 'provider') { 'PROVIDER_VERIFIED' } else { 'QQ_API_ACCEPTED_CHECK_CLIENT' }
            }
        }
        $exitCode = 0
    } catch {
        $code = $_.Exception.Message
        if ($code -cnotmatch '^[A-Z0-9_]{1,80}$') { $code = 'WORKFLOW_STOPPED' }
        $summary['code'] = $code
        Write-Host ('已停止：' + $code + '。不自动重试、不清理或复用批准。')
    } finally {
        if ($directory) {
            try { Write-BotJsonNew (Join-Path $directory 'summary.json') $summary }
            catch { $exitCode = 1; Write-Host '摘要保存失败；请保留本次目录，停止后续操作。' }
            Write-Host ('本次记录：' + $directory)
        }
        Write-Host ('结果：' + $summary.status)
        if ($pushed) { Pop-Location }
    }
    return $exitCode
}
