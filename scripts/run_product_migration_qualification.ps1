# P2E fixed index only. No Provider execution without this invocation's consent.
[CmdletBinding()]
param([switch]$ConfirmNetwork)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'projection_qualification_runner.ps1')

function Stop-P2E {
    param([string]$Code)
    throw "$Code`: stopped; inventory safe reports before any further run. No automatic resume."
}

function Assert-P2EBoundary {
    param([string]$Path, [string]$Root)
    $current = [IO.Path]::GetFullPath($Path)
    if (-not $current.StartsWith($Root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        Stop-P2E 'QUALIFICATION_REPORT_PATH_INVALID'
    }
    while (-not [string]::Equals($current, $Root, [StringComparison]::OrdinalIgnoreCase)) {
        Assert-QualificationPath $current
        $current = Split-Path -Parent $current
    }
    Assert-QualificationPath $Root
}

function Get-P2EReports {
    param([string]$Folder, [string]$Root)
    Assert-P2EBoundary $Folder $Root
    $files = @()
    if (-not (Test-Path -LiteralPath $Folder)) { return $files }
    $queue = @($Folder)
    while ($queue.Count -gt 0) {
        $next = @()
        foreach ($directory in $queue) {
            foreach ($item in (Get-ChildItem -LiteralPath $directory -Force)) {
                Assert-P2EBoundary $item.FullName $Root
                if ($item.PSIsContainer) { $next += $item.FullName }
                elseif ($item.Extension -eq '.json') { $files += $item.FullName }
                else { Stop-P2E 'QUALIFICATION_UNEXPECTED_OUTPUT' }
            }
        }
        $queue = $next
    }
    return $files
}

function Invoke-P2EConditions {
    param([string]$Python)
    # Read the existing static Registry, never credentials or a Provider.
    $code = "import json,hashlib; from fishery_ai.assistant_qualification import _registry; from fishery_ai.assistant import SYSTEM_INSTRUCTION; from fishery_ai.qualification_projection import tool_schema_hash; print(json.dumps({'schema':tool_schema_hash(_registry().model_definitions()),'system':hashlib.sha256(SYSTEM_INSTRUCTION.encode('utf-8')).hexdigest()}))"
    $lines = @(& $Python '-c' $code 2>&1)
    $exit = $LASTEXITCODE
    try { $data = ($lines -join "`n") | ConvertFrom-Json -ErrorAction Stop }
    catch { Stop-P2E 'QUALIFICATION_CONDITIONS_INVALID' }
    if ($exit -ne 0) { Stop-P2E 'QUALIFICATION_CONDITIONS_INVALID' }
    return $data
}

function Assert-P2EPlan {
    param([object]$Plan, [object]$Item)
    if ($null -eq $Plan -or $Plan.case_id -cne $Item.case_id -or
            $Plan.plan_sha256 -cne $Item.plan_sha256 -or
            $Plan.retry -ne 0 -or $Plan.max_requests -ne 2 -or
            $Plan.max_output_tokens_per_request -ne 256 -or
            $Plan.thinking -cne 'OFF' -or $Plan.response_mode -cne 'Normal' -or
            $Plan.system_instruction_sha256 -cne $fixedSystem -or
            (@($Plan.exposed_tools) -join ',') -cne $fixedTools) {
        Stop-P2E 'QUALIFICATION_PLAN_CHANGED'
    }
    if ($Item.case_id -cnotmatch '^P2E-(QWEN|DEEPSEEK|OLLAMA)-(S[1-7](?:O|K)?)-([AB])$') {
        Stop-P2E 'QUALIFICATION_PLAN_INVALID'
    }
    $arm = $Matches[3]
    $projection = if ($arm -ceq 'A') { 'CURRENT_NATIVE' } else { 'UNTRUSTED_TRANSCRIPT_V1' }
    if ($Plan.projection_id -cne $projection -or $Plan.projection_version -cne '1') {
        Stop-P2E 'QUALIFICATION_PLAN_CHANGED'
    }
}

function Assert-P2EReportPlan {
    param([object]$Actual, [object]$Expected)
    if ($null -eq $Actual -or $Actual.network -cne 'AUTHORIZED_FOR_THIS_RUN' -or
            @($Actual.PSObject.Properties).Count -ne @($Expected.PSObject.Properties).Count) {
        Stop-P2E 'QUALIFICATION_IDENTITY_MISMATCH'
    }
    foreach ($property in $Expected.PSObject.Properties) {
        if ($property.Name -ceq 'network') { continue }
        $value = $Actual.PSObject.Properties[$property.Name]
        if ($null -eq $value) { Stop-P2E 'QUALIFICATION_IDENTITY_MISMATCH' }
        if ($property.Name -ceq 'identity') {
            foreach ($key in @('service_id','adapter_id','base_url','model')) {
                if ($value.Value.$key -cne $property.Value.$key) { Stop-P2E 'QUALIFICATION_IDENTITY_MISMATCH' }
            }
        } elseif ((ConvertTo-Json -InputObject $value.Value -Compress -Depth 20) -cne
                (ConvertTo-Json -InputObject $property.Value -Compress -Depth 20)) {
            Stop-P2E 'QUALIFICATION_IDENTITY_MISMATCH'
        }
    }
}

$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\', '/')
if (-not [string]::Equals((Get-Location).ProviderPath.TrimEnd('\', '/'), $root,
        [StringComparison]::OrdinalIgnoreCase) -or -not (Test-Path -LiteralPath (Join-Path $root 'pyproject.toml') -PathType Leaf)) {
    Stop-P2E 'WORKSPACE_REQUIRED'
}
$python = Join-Path $root '.venv\Scripts\python.exe'
$cli = Join-Path $root 'scripts\qualify_assistant_turn.py'
foreach ($path in @($python, $cli)) {
    Assert-P2EBoundary $path $root
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Stop-P2E 'QUALIFICATION_CLI_MISSING' }
}
$indexPath = Join-Path $root 'scripts\manifests\product-migration\qualification-plan.json'
Assert-P2EBoundary $indexPath $root
if (-not (Test-Path -LiteralPath $indexPath -PathType Leaf)) { Stop-P2E 'QUALIFICATION_PLAN_MISSING' }
# Pin the approved index bytes, not a second hand-copied list of positions.
if ((Get-FileHash -LiteralPath $indexPath -Algorithm SHA256).Hash -cne
        '5153DD52F3F0E335493C1ABE9B8AB2A1D5579CD29A82B515BD48960E98BD1718') {
    Stop-P2E 'QUALIFICATION_INDEX_CHANGED'
}
try { $index = [IO.File]::ReadAllText($indexPath) | ConvertFrom-Json -ErrorAction Stop }
catch { Stop-P2E 'QUALIFICATION_PLAN_INVALID' }
$order = @($index.order)
if ($order.Count -ne 30 -or $index.study -cne 'P2E' -or $index.max_runs -ne 30 -or
        $index.max_provider_requests -ne 60 -or $index.max_requests_per_run -ne 2 -or
        $index.max_output_tokens_per_request -ne 256 -or $index.retry -ne 0) { Stop-P2E 'QUALIFICATION_PLAN_INVALID' }
$fixedSchema = '2f1c15a25dcfceb5225f52ba544656c08242fed3c6e1b118775f8b37c233a050'
$fixedSystem = '974cc942da1a909ee2f41c74aeb329fbfafe7aacd309aaeff90c9541e2843bc5'
$fixedTools = 'get_current_water_quality,score_current_water_quality,search_fishery_knowledge'
$reportsRoot = Join-Path $root 'outputs\assistant-qualification\product-migration'
$knownFiles = @{}
$runIds = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
foreach ($file in @(Get-P2EReports $reportsRoot $root)) {
    try { $old = [IO.File]::ReadAllText($file) | ConvertFrom-Json -ErrorAction Stop }
    catch { Stop-P2E 'QUALIFICATION_REPORT_INVALID' }
    if ($null -eq $old.actual_network_requests -or $old.actual_network_requests -notin @(0,1,2)) {
        Stop-P2E 'QUALIFICATION_REPORT_INVALID'
    }
    if ($old.actual_network_requests -gt 0) { Stop-P2E 'QUALIFICATION_ALREADY_RUN' }
    $knownFiles[$file] = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
    if ($old.run_id -and -not $runIds.Add([string]$old.run_id)) { Stop-P2E 'QUALIFICATION_DUPLICATE_RUN_ID' }
}
$conditions = Invoke-P2EConditions $python
if ($conditions.schema -cne $fixedSchema -or $conditions.system -cne $fixedSystem) {
    Stop-P2E 'QUALIFICATION_CONDITIONS_CHANGED'
}
$plans = @{}
for ($offset = 0; $offset -lt $order.Count; $offset++) {
    $item = $order[$offset]
    if ($item.position -ne $offset + 1 -or $plans.ContainsKey([string]$item.case_id) -or
            $item.manifest -cne "scripts/manifests/product-migration/assistant-$($item.case_id).json") {
        Stop-P2E 'QUALIFICATION_PLAN_INVALID'
    }
    $manifestPath = Join-Path $root $item.manifest
    Assert-P2EBoundary $manifestPath $root
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { Stop-P2E 'QUALIFICATION_MANIFEST_MISSING' }
    $preview = Invoke-QualificationProcess -Python $python -Manifest $item.manifest
    if ($preview.ExitCode -ne 0 -or $preview.Data.dry_run -ne $true -or $preview.Data.actual_network_requests -ne 0) {
        Stop-P2E 'QUALIFICATION_DRY_RUN_INVALID'
    }
    Assert-P2EPlan $preview.Data.plan $item
    $plans[$item.case_id] = $preview.Data.plan
}
Write-Host 'P2E PRODUCT-MIGRATION QUALIFICATION'
Write-Host 'TOTAL POSITIONS: 30'
Write-Host 'MAX PROVIDER REQUESTS: 60'
Write-Host 'QWEN RUNS: 16'
Write-Host 'DEEPSEEK RUNS: 6'
Write-Host 'OLLAMA RUNS: 8'
Write-Host 'ORDER: FIXED / CROSS-MODEL'
Write-Host 'RETRY: 0'
Write-Host 'NO FAILED SAMPLE WILL BE RE-RUN'
Write-Host 'NO AUTOMATIC RESUME'
if (-not $ConfirmNetwork) {
    Write-Host 'PREPARED: 30 runs / max 60 requests / Provider requests = 0'
    return
}
$hardStops = @('CREDENTIAL_FILE_ERROR','SECRET_MISSING','QUALIFICATION_UNSAFE_LOGGING',
    'QUALIFICATION_REPORT_ERROR','USER_CANCELLED','QUALIFICATION_FAILED','QUALIFICATION_INVALID_TRANSPORT',
    'QUALIFICATION_IDENTITY_MISMATCH','MODEL_IDENTITY_MISMATCH','QUALIFICATION_NORMALIZATION_MISMATCH',
    'QUALIFICATION_PROJECTION_MISMATCH','QUALIFICATION_REQUEST_LIMIT','QUALIFICATION_TOKEN_BUDGET_UNAVAILABLE',
    'CONNECT_TIMEOUT','READ_TIMEOUT','TOTAL_TIMEOUT','TIMEOUT','DNS_ERROR','TLS_ERROR','PROXY_ERROR',
    'CONNECTION_ERROR','SDK_ERROR','TRACE_WRITE_ERROR')
$behaviorFailures = @('INVALID_RESPONSE','INVALID_TOOL_CALL','MODEL_TOOL_CALL_MALFORMED',
    'TOOL_CALL_LIMIT','TOOL_ROUND_LIMIT','UNKNOWN_TOOL','TOOL_NOT_ALLOWED',
    'INVALID_TOOL_ARGUMENTS','TOOL_EXECUTION_ERROR','TOOL_RESULT_TOO_LARGE',
    'OPTION_UNKNOWN','OPTION_UNSUPPORTED','OPTION_CONFLICT','TOOL_UNSUPPORTED',
    'THINKING_UNSUPPORTED','ASSISTANT_SOURCE_REQUIREMENT_UNMET','ASSISTANT_RESPONSE_EMPTY',
    'ASSISTANT_RESPONSE_TRUNCATED','ASSISTANT_RESPONSE_INCOMPLETE',
    'ASSISTANT_PRESET_NOT_ALLOWED','ASSISTANT_PRESET_NOT_AVAILABLE',
    'MODEL_REQUEST_ERROR','TOOL_CONVERSATION_ERROR','NETWORK_CONFIRMATION_REQUIRED')
$actualTotal = 0
foreach ($item in $order) {
    # Frozen plan and schema are rechecked before this one independent process.
    if ((Get-FileHash -LiteralPath $indexPath -Algorithm SHA256).Hash -cne
            '5153DD52F3F0E335493C1ABE9B8AB2A1D5579CD29A82B515BD48960E98BD1718') { Stop-P2E 'QUALIFICATION_INDEX_CHANGED' }
    $conditions = Invoke-P2EConditions $python
    if ($conditions.schema -cne $fixedSchema -or $conditions.system -cne $fixedSystem) { Stop-P2E 'QUALIFICATION_CONDITIONS_CHANGED' }
    $preview = Invoke-QualificationProcess -Python $python -Manifest $item.manifest
    if ($preview.ExitCode -ne 0 -or $preview.Data.dry_run -ne $true -or $preview.Data.actual_network_requests -ne 0) { Stop-P2E 'QUALIFICATION_DRY_RUN_INVALID' }
    Assert-P2EPlan $preview.Data.plan $item
    $run = Invoke-QualificationProcess -Python $python -Manifest $item.manifest -Network
    $summary = $run.Data
    if ($item.case_id -cnotmatch '^P2E-(QWEN|DEEPSEEK|OLLAMA)-(S[1-7](?:O|K)?)-([AB])$') { Stop-P2E 'QUALIFICATION_PLAN_INVALID' }
    $partition = "$($Matches[1].ToLowerInvariant())/$($Matches[2].ToLowerInvariant())/$($Matches[3].ToLowerInvariant())"
    $prefix = 'outputs/assistant-qualification/product-migration/' + $partition + '/'
    if ($run.ExitCode -notin @(0,1) -or $summary.report -isnot [string] -or
            $summary.report -cnotmatch ('^' + [regex]::Escape($prefix) + '[a-f0-9]{32}\.json$')) {
        Stop-P2E 'QUALIFICATION_CLI_REPORT_INVALID'
    }
    $reportPath = [IO.Path]::GetFullPath((Join-Path $root $summary.report))
    Assert-P2EBoundary $reportPath $root
    if (-not $reportPath.StartsWith($reportsRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or
            $knownFiles.ContainsKey($reportPath)) { Stop-P2E 'QUALIFICATION_REPORT_PATH_INVALID' }
    try { $safe = [IO.File]::ReadAllText($reportPath) | ConvertFrom-Json -ErrorAction Stop }
    catch { Stop-P2E 'QUALIFICATION_REPORT_INVALID' }
    Assert-P2EReportPlan $safe.plan $plans[$item.case_id]
    if ($safe.status -cnotin @('completed','failed','cancelled') -or $safe.success -isnot [bool] -or
            ($null -ne $safe.error_code -and $safe.error_code -cnotin ($hardStops + $behaviorFailures) -and
                $safe.error_code -cnotmatch '^HTTP_[1-5][0-9]{2}$')) {
        Stop-P2E 'QUALIFICATION_REPORT_INVALID'
    }
    if ($safe.run_id -cne $summary.run_id -or $safe.run_id -cne [IO.Path]::GetFileNameWithoutExtension($reportPath) -or
            -not $runIds.Add([string]$safe.run_id) -or $safe.request_count -notin @(0,1,2) -or
            $safe.actual_network_requests -notin @(0,1,2) -or $safe.transport_attempts -ne $safe.actual_network_requests -or
            $safe.actual_network_requests -gt $safe.request_count -or @($safe.requests).Count -ne $safe.request_count -or
            $safe.actual_network_requests -ne $summary.actual_network_requests -or
            $safe.request_count -ne $summary.request_count -or $safe.status -cne $summary.status -or
            $safe.error_code -cne $summary.error_code -or $safe.success -ne $summary.success -or
            ($run.ExitCode -eq 0) -ne ($safe.success -eq $true)) { Stop-P2E 'QUALIFICATION_REPORT_IDENTITY_OR_BUDGET_INVALID' }
    $requestNumber = 0
    foreach ($row in @($safe.requests)) {
        $requestNumber++
        if ($row.request_number -ne $requestNumber -or $row.request_number -notin @(1,2) -or $row.tool_schema_sha256 -cne $fixedSchema -or (@($row.tool_definitions) -join ',') -cne $fixedTools -or
                $row.knowledge_schema_required_query -ne $true -or
                $row.tool_choice -cne $(if ($row.request_number -eq 1) { 'auto' } else { 'none' }) -or
                $row.provider_observation.provider_model_matches -eq $false -or
                $row.normalized.provider_model_matches -eq $false -or
                $row.provider_observation.normalized_call_consistent -eq $false -or
                $row.provider_observation.normalized_metadata_consistent -eq $false) { Stop-P2E 'QUALIFICATION_PROVIDER_IDENTITY_OR_PROTOCOL_INVALID' }
    }
    foreach ($oldPath in $knownFiles.Keys) {
        Assert-P2EBoundary $oldPath $root
        if (-not (Test-Path -LiteralPath $oldPath) -or
                (Get-FileHash -LiteralPath $oldPath -Algorithm SHA256).Hash -cne $knownFiles[$oldPath]) { Stop-P2E 'QUALIFICATION_REPORT_OVERWRITTEN' }
    }
    $knownFiles[$reportPath] = (Get-FileHash -LiteralPath $reportPath -Algorithm SHA256).Hash
    $filesNow = @(Get-P2EReports $reportsRoot $root)
    if ($filesNow.Count -ne $knownFiles.Count -or @($filesNow | Where-Object { -not $knownFiles.ContainsKey($_) }).Count -gt 0) {
        Stop-P2E 'QUALIFICATION_UNEXPECTED_OUTPUT'
    }
    $actualTotal += $safe.actual_network_requests
    if ($actualTotal -gt 60) { Stop-P2E 'QUALIFICATION_REQUEST_LIMIT' }
    Write-Host "$($item.position)/30 $($item.case_id) : $($safe.status) / $($safe.error_code) / requests=$($safe.actual_network_requests)"
    if ($safe.error_code -in $hardStops -or $safe.error_code -cmatch '^HTTP_[1-5][0-9]{2}$') { Stop-P2E 'QUALIFICATION_BATCH_STOPPED' }
}
Write-Host "P2E COMPLETED: 30 runs / $actualTotal requests; stop, no repeat."
