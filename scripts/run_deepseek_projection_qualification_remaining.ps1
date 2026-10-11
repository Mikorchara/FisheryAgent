# One-time continuation for the audited DeepSeek P2D state only.
# It accepts exactly one completed real sample at fixed position 1.
[CmdletBinding()]
param([switch]$ConfirmNetwork)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'projection_qualification_runner.ps1')

function Stop-Continuation {
    param([string]$Code)
    throw "$Code`: continuation stopped; inspect local safe reports before any further run."
}

function Assert-DeepSeekReportIdentity {
    param([object]$Report, [string]$Path, [hashtable]$Hashes, [string]$WorkspaceRoot)
    if ($null -eq $Report -or $null -eq $Report.plan) { Stop-Continuation 'QUALIFICATION_REPORT_INVALID' }
    $caseId = [string]$Report.plan.case_id
    if (-not $Hashes.ContainsKey($caseId) -or $Report.plan.plan_sha256 -ne $Hashes[$caseId]) {
        Stop-Continuation 'QUALIFICATION_PLAN_INVALID'
    }
    # Projection and requirement belong to the case, not to Provider identity.
    $expectedProjection = if ($caseId.EndsWith('-B')) { 'UNTRUSTED_TRANSCRIPT_V1' } else { 'CURRENT_NATIVE' }
    $expectedRequirement = if ($caseId.StartsWith('DEEPSEEK-H5-')) { 'AUTO' } else { 'CURRENT_OBSERVATION_QUERY' }
    $identity = $Report.plan.identity
    if ($Report.plan.preset_id -ne 'deepseek-flash-r1' -or
            $Report.plan.contract_version -ne '1.0.2' -or
            $identity.service_id -ne 'deepseek_api' -or $identity.adapter_id -ne 'openai_chat' -or
            $identity.base_url -ne 'https://api.deepseek.com' -or $identity.model -ne 'deepseek-flash' -or
            $Report.plan.protocol_spec_id -ne 'deepseek_chat' -or
            $Report.plan.protocol_spec_version -ne '1' -or
            $Report.plan.thinking -ne 'OFF' -or $Report.plan.response_mode -ne 'Normal' -or
            $Report.plan.max_requests -ne 2 -or $Report.plan.max_output_tokens_per_request -ne 256 -or
            $Report.plan.retry -ne 0 -or
            $Report.plan.source_requirement -cne $expectedRequirement -or
            $Report.plan.projection_id -cne $expectedProjection -or
            (@($Report.plan.exposed_tools) -join ',') -ne
                'get_current_water_quality,score_current_water_quality,search_fishery_knowledge') {
        Stop-Continuation 'QUALIFICATION_IDENTITY_MISMATCH'
    }
    $expectedDirectory = if ($caseId -eq 'DEEPSEEK-H2F') { 'h2fresh' }
        elseif ($caseId -match '^DEEPSEEK-(H2|H5)-([AB])$') { "$($Matches[1].ToLower())/$($Matches[2].ToLower())" }
        else { Stop-Continuation 'QUALIFICATION_REPORT_CASE_INVALID' }
    $expectedPrefix = [IO.Path]::GetFullPath((Join-Path $WorkspaceRoot "outputs\assistant-qualification\cross-model\deepseek\$expectedDirectory")) + [IO.Path]::DirectorySeparatorChar
    $fullPath = [IO.Path]::GetFullPath($Path)
    if (-not $fullPath.StartsWith($expectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        Stop-Continuation 'QUALIFICATION_REPORT_CASE_PATH_INVALID'
    }
    $fileId = [IO.Path]::GetFileNameWithoutExtension($fullPath)
    if ($fileId -notmatch '^[a-f0-9]{32}$' -or $Report.run_id -ne $fileId) {
        Stop-Continuation 'QUALIFICATION_REPORT_INVALID'
    }
    if ($Report.request_count -notin @(0, 1, 2) -or $Report.actual_network_requests -notin @(0, 1, 2) -or
            $Report.transport_attempts -notin @(0, 1, 2) -or
            $Report.actual_network_requests -ne $Report.transport_attempts -or
            @($Report.requests).Count -ne $Report.request_count) {
        Stop-Continuation 'QUALIFICATION_REQUEST_BUDGET_INVALID'
    }
}

$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\', '/')
if (-not [string]::Equals((Get-Location).ProviderPath.TrimEnd('\', '/'), $root,
        [StringComparison]::OrdinalIgnoreCase) -or
        -not (Test-Path -LiteralPath (Join-Path $root 'pyproject.toml') -PathType Leaf)) {
    Stop-Continuation 'WORKSPACE_REQUIRED'
}
$python = Join-Path $root '.venv\Scripts\python.exe'
$cli = Join-Path $root 'scripts\qualify_assistant_turn.py'
if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or
        -not (Test-Path -LiteralPath $cli -PathType Leaf)) {
    Stop-Continuation 'QUALIFICATION_CLI_MISSING'
}

$hashes = @{
    'DEEPSEEK-H2-A' = '3bd3d342315a53afe82a42cdfb715846eb657b4ecf463420dc9b6cb0d3510a72'
    'DEEPSEEK-H2-B' = 'a144baec7d8ed58ef9162342f6f61b2ac83267e3421e0b5db527d94d03db1c0d'
    'DEEPSEEK-H2F' = '05a3a3dc1b12b479858c4ca7e569f70c2f6bb38e56a0c6f2e3e3bdcff8274df9'
    'DEEPSEEK-H5-A' = '33d42c5cdc9148bd5db2dbe7dcf1971c01c6e0c96a6ea1d3f96c6b27d79598c9'
    'DEEPSEEK-H5-B' = '04ab561c4f022dd86a627d6ddb732b8d160c3f1eac5eaf2836f725e852f02f42'
}
$schedulePath = Join-Path $root 'outputs\assistant-qualification\cross-model\deepseek\run-order.txt'
Assert-QualificationPath $schedulePath
if (-not (Test-Path -LiteralPath $schedulePath -PathType Leaf)) { Stop-Continuation 'QUALIFICATION_ORDER_MISSING' }
$sha = [Security.Cryptography.SHA256]::Create()
try { $scheduleHash = [BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($schedulePath))).Replace('-', '').ToLowerInvariant() }
finally { $sha.Dispose() }
if ($scheduleHash -cne 'beaecf58bd9e412ab079f691f58a27e98dc27f17b16e5e63d4ae96bc2c17ccfd') {
    Stop-Continuation 'QUALIFICATION_ORDER_CHANGED'
}
$order = @([IO.File]::ReadAllLines($schedulePath))
if ($order.Count -ne 30 -or $order[0] -cne 'DEEPSEEK-H2F' -or
        ($order | Where-Object { -not $hashes.ContainsKey($_) }).Count -ne 0) {
    Stop-Continuation 'QUALIFICATION_ORDER_INVALID'
}

$reportsRoot = Join-Path $root 'outputs\assistant-qualification\cross-model\deepseek'
$boundary = $root
foreach ($part in @('outputs', 'assistant-qualification', 'cross-model', 'deepseek')) {
    $boundary = Join-Path $boundary $part
    Assert-QualificationPath $boundary
    if (-not (Test-Path -LiteralPath $boundary -PathType Container)) {
        Stop-Continuation 'QUALIFICATION_REPORTS_MISSING'
    }
}
$rootPrefix = [IO.Path]::GetFullPath($reportsRoot).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
Assert-QualificationPath $reportsRoot
if (-not (Test-Path -LiteralPath $reportsRoot -PathType Container)) { Stop-Continuation 'QUALIFICATION_REPORTS_MISSING' }
$directories = @((Get-Item -LiteralPath $reportsRoot -Force))
$jsonReports = @()
$runIds = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
while ($directories.Count -gt 0) {
    $nextDirectories = @()
    foreach ($directory in $directories) {
        foreach ($item in (Get-ChildItem -LiteralPath $directory.FullName -Force)) {
            Assert-QualificationPath $item.FullName
            if ($item.PSIsContainer) { $nextDirectories += $item; continue }
            if ($item.FullName -eq $schedulePath) { continue }
            if ($item.Extension -ne '.json') { Stop-Continuation 'QUALIFICATION_UNEXPECTED_OUTPUT' }
            $jsonReports += $item
        }
    }
    $directories = $nextDirectories
}

$existingReal = @()
foreach ($file in $jsonReports) {
    try { $safe = [IO.File]::ReadAllText($file.FullName) | ConvertFrom-Json -ErrorAction Stop }
    catch { Stop-Continuation 'QUALIFICATION_REPORT_INVALID' }
    Assert-DeepSeekReportIdentity $safe $file.FullName $hashes $root
    if (-not $runIds.Add([string]$safe.run_id)) { Stop-Continuation 'QUALIFICATION_DUPLICATE_RUN_ID' }
    if ($safe.actual_network_requests -gt 0) { $existingReal += @{File=$file;Report=$safe} }
}
if ($existingReal.Count -ne 1) { Stop-Continuation 'QUALIFICATION_EXISTING_SAMPLE_COUNT_INVALID' }
$first = $existingReal[0]
if ($order[0] -cne 'DEEPSEEK-H2F' -or $first.Report.plan.case_id -cne $order[0] -or
        $first.Report.plan.plan_sha256 -cne $hashes[$order[0]] -or
        $first.Report.status -cne 'completed' -or $first.Report.success -ne $true -or
        $null -ne $first.Report.error_code -or $first.Report.request_count -ne 2 -or
        $first.Report.actual_network_requests -ne 2 -or $first.Report.transport_attempts -ne 2 -or
        $first.Report.plan.history_fixture_id -cne 'EMPTY' -or
        $first.Report.plan.question_sha256 -cne '4006f49117be4d1349b5fe005bfe6adf95207989448dae8cefe19eed13500ac7') {
    Stop-Continuation 'QUALIFICATION_FIRST_SAMPLE_INVALID'
}

# The audited report must prove the completed two-request round trip, not only its run totals.
$firstRequests = @($first.Report.requests)
$firstReceipt = $first.Report.receipt
if ($firstRequests.Count -ne 2 -or
        $firstRequests[0].provider_observation.available -ne $true -or
        $firstRequests[0].provider_observation.provider_model_matches -ne $true -or
        $firstRequests[0].provider_observation.finish_reason -cne 'tool_calls' -or
        $firstRequests[0].provider_observation.tool_call_count -ne 1 -or
        $firstRequests[0].normalized.calls[0].function_name -cne 'get_current_water_quality' -or
        $firstRequests[0].normalized.calls[0].call_id_valid -ne $true -or
        $firstRequests[0].normalized.calls[0].arguments_valid -ne $true -or
        $firstRequests[0].provider_observation.normalized_call_consistent -ne $true -or
        $firstRequests[1].provider_observation.finish_reason -cne 'stop' -or
        $firstRequests[1].provider_observation.tool_calls_present -ne $false -or
        $firstReceipt.tool_status -cne 'NO_DATA' -or
        $firstReceipt.observation_query_completed -ne $true -or
        $first.Report.requirement_satisfied -ne $true -or
        $first.Report.final_answer_present -ne $true -or
        $first.Report.final_finish_reason -cne 'stop') {
    Stop-Continuation 'QUALIFICATION_FIRST_SAMPLE_EVIDENCE_INVALID'
}

# Re-check all five fixed plans with the real CLI before any network request.
$plans = @{}
foreach ($caseId in $hashes.Keys) {
    $manifest = "scripts/manifests/assistant-$caseId.json"
    if (-not (Test-Path -LiteralPath (Join-Path $root $manifest) -PathType Leaf)) {
        Stop-Continuation 'QUALIFICATION_MANIFEST_MISSING'
    }
    try { $preview = Invoke-QualificationProcess -Python $python -Manifest $manifest }
    catch { Stop-Continuation 'QUALIFICATION_DRY_RUN_INVALID' }
    if ($preview.ExitCode -ne 0 -or $preview.Data.dry_run -ne $true -or
            $preview.Data.actual_network_requests -ne 0 -or $preview.Data.plan.case_id -cne $caseId -or
            $preview.Data.plan.plan_sha256 -cne $hashes[$caseId] -or
            $preview.Data.plan.max_requests -ne 2 -or
            $preview.Data.plan.max_output_tokens_per_request -ne 256 -or $preview.Data.plan.retry -ne 0) {
        Stop-Continuation 'QUALIFICATION_PLAN_CHANGED'
    }
    $plans[$caseId] = $preview.Data.plan
}
if ($first.Report.plan.question_sha256 -cne $plans['DEEPSEEK-H2F'].question_sha256 -or
        $first.Report.plan.projection_definition_sha256 -cne $plans['DEEPSEEK-H2F'].projection_definition_sha256 -or
        $first.Report.plan.history_fixture_sha256 -cne $plans['DEEPSEEK-H2F'].history_fixture_sha256) {
    Stop-Continuation 'QUALIFICATION_FIRST_SAMPLE_PLAN_MISMATCH'
}

Write-Host 'DEEPSEEK CONTINUATION AUDIT PASSED'
Write-Host 'EXISTING REAL RUNS: 1/30'
Write-Host 'COMPLETED POSITION: 1'
Write-Host 'COMPLETED CASE: DEEPSEEK-H2F'
Write-Host 'NEXT POSITION: 2/30'
Write-Host 'REMAINING RUNS: 29'
Write-Host 'MAX REMAINING REQUESTS: 58'
Write-Host 'FIRST SAMPLE WILL NOT BE RE-RUN'
if (-not $ConfirmNetwork) {
    Write-Host 'DRY RUN ONLY: no Provider requests were made.'
    return
}

$hardStops = @('CREDENTIAL_FILE_ERROR', 'SECRET_MISSING', 'QUALIFICATION_UNSAFE_LOGGING',
    'QUALIFICATION_REPORT_ERROR', 'QUALIFICATION_CLI_REPORT_INVALID', 'QUALIFICATION_IDENTITY_MISMATCH', 'USER_CANCELLED')
$actualTotal = 0
for ($index = 1; $index -lt $order.Count; $index++) {
    $caseId = $order[$index]
    $manifest = "scripts/manifests/assistant-$caseId.json"
    try { $preview = Invoke-QualificationProcess -Python $python -Manifest $manifest }
    catch { Stop-Continuation 'QUALIFICATION_DRY_RUN_INVALID' }
    if ($preview.ExitCode -ne 0 -or $preview.Data.dry_run -ne $true -or
            $preview.Data.actual_network_requests -ne 0 -or
            $preview.Data.plan.plan_sha256 -cne $hashes[$caseId]) { Stop-Continuation 'QUALIFICATION_PLAN_CHANGED' }

    # Exactly one confirmed CLI process per scheduled slot. Never retry this call.
    try { $run = Invoke-QualificationProcess -Python $python -Manifest $manifest -Network }
    catch { Stop-Continuation 'QUALIFICATION_CLI_OUTPUT_INVALID' }
    $summary = $run.Data
    if ($run.ExitCode -notin @(0, 1) -or $summary.report -isnot [string] -or
            $summary.report -notmatch '^outputs/assistant-qualification/cross-model/deepseek/') {
        Stop-Continuation 'QUALIFICATION_CLI_REPORT_INVALID'
    }
    $reportPath = [IO.Path]::GetFullPath((Join-Path $root $summary.report))
    if (-not $reportPath.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        Stop-Continuation 'QUALIFICATION_REPORT_OUTSIDE_MODEL'
    }
    $parent = $reportPath
    while (-not [string]::Equals([IO.Path]::GetFullPath($parent), [IO.Path]::GetFullPath($reportsRoot),
            [StringComparison]::OrdinalIgnoreCase)) {
        Assert-QualificationPath $parent
        $parent = Split-Path -Parent $parent
        if (-not [string]::Equals([IO.Path]::GetFullPath($parent), [IO.Path]::GetFullPath($reportsRoot),
                [StringComparison]::OrdinalIgnoreCase) -and
                -not $parent.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            Stop-Continuation 'QUALIFICATION_REPORT_PARENT_INVALID'
        }
    }
    try { $safe = [IO.File]::ReadAllText($reportPath) | ConvertFrom-Json -ErrorAction Stop }
    catch { Stop-Continuation 'QUALIFICATION_REPORT_INVALID' }
    Assert-DeepSeekReportIdentity $safe $reportPath $hashes $root
    if ($safe.plan.case_id -cne $caseId -or $safe.plan.plan_sha256 -cne $plans[$caseId].plan_sha256 -or
            $safe.run_id -cne $summary.run_id -or
            $safe.actual_network_requests -ne $summary.actual_network_requests -or
            $safe.error_code -ne $summary.error_code -or $safe.actual_network_requests -gt 2) {
        Stop-Continuation 'QUALIFICATION_REPORT_IDENTITY_OR_BUDGET_INVALID'
    }
    if (-not $runIds.Add([string]$safe.run_id)) { Stop-Continuation 'QUALIFICATION_DUPLICATE_RUN_ID' }
    $actualTotal += $safe.actual_network_requests
    Write-Host "$($index + 1)/30 $caseId : $($safe.status) / $($safe.error_code) / requests=$($safe.actual_network_requests)"
    if ($safe.error_code -in $hardStops) { Stop-Continuation 'QUALIFICATION_BATCH_STOPPED' }
}
Write-Host "DEEPSEEK CONTINUATION COMPLETED: 29 runs / $actualTotal requests; first sample preserved."
