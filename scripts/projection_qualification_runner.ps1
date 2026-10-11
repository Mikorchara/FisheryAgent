# Shared scheduling only. Each model entry owns its fixed hashes and consent.
# No Credential reads, no model-specific Assistant behavior, no Provider retry.
function Invoke-QualificationProcess {
    param([string]$Python, [string]$Manifest, [switch]$Network)
    $mode = if ($Network) { '--confirm-network' } else { '--dry-run' }
    $lines = @(& $Python 'scripts/qualify_assistant_turn.py' '--manifest' $Manifest $mode 2>&1)
    $exitCode = $LASTEXITCODE
    try { $parsed = ($lines -join "`n") | ConvertFrom-Json -ErrorAction Stop }
    catch { throw 'QUALIFICATION_CLI_OUTPUT_INVALID: stopped; review before running again.' }
    return @{ Data = $parsed; ExitCode = $exitCode }
}

function Assert-QualificationPath {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) {
        $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'QUALIFICATION_OUTPUT_BOUNDARY_UNSAFE: stopped.'
        }
    }
}

function Invoke-ProjectionQualificationBatch {
    param(
        [Parameter(Mandatory)][ValidateSet('deepseek', 'ollama')][string]$ModelKey,
        [Parameter(Mandatory)][hashtable]$ExpectedHashes,
        [Parameter(Mandatory)][string]$ProjectRoot,
        [switch]$ConfirmNetwork
    )
    $ErrorActionPreference = 'Stop'
    $root = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\', '/')
    if (-not [string]::Equals((Get-Location).ProviderPath.TrimEnd('\', '/'), $root,
            [StringComparison]::OrdinalIgnoreCase) -or
            -not (Test-Path -LiteralPath (Join-Path $root 'pyproject.toml') -PathType Leaf)) {
        throw 'WORKSPACE_REQUIRED: run from the project root.'
    }
    $python = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw 'QUALIFICATION_PYTHON_MISSING: activate/install the project environment manually.'
    }
    $prefix = $ModelKey.ToUpperInvariant()
    $conditions = @('H2F', 'H2-A', 'H2-B', 'H5-A', 'H5-B')
    if ($ExpectedHashes.Count -ne 5) { throw 'QUALIFICATION_PLAN_INVALID: stopped.' }
    $order = @('H2F', 'H2F', 'H2F')
    for ($pair = 1; $pair -le 6; $pair++) {
        $arms = if ($pair % 2 -eq 1) { @('A', 'B') } else { @('B', 'A') }
        foreach ($case in @('H2', 'H5')) {
            foreach ($arm in $arms) { $order += "$case-$arm" }
        }
    }
    $order += @('H2F', 'H2F', 'H2F')
    if ($order.Count -ne 30) { throw 'QUALIFICATION_ORDER_INVALID: stopped.' }
    $order = @($order | ForEach-Object { "$prefix-$_" })
    $boundary = $root
    Assert-QualificationPath $boundary
    foreach ($part in @('outputs', 'assistant-qualification', 'cross-model', $ModelKey)) {
        $boundary = Join-Path $boundary $part
        Assert-QualificationPath $boundary
    }
    $reports = $boundary
    # Do not follow a reparse point while inventorying previous reports.
    if (Test-Path -LiteralPath $reports) {
        $directories = @((Get-Item -LiteralPath $reports))
        while ($directories.Count -gt 0) {
            $next = @()
            foreach ($directory in $directories) {
                foreach ($item in (Get-ChildItem -LiteralPath $directory.FullName -Force)) {
                    Assert-QualificationPath $item.FullName
                    if ($item.PSIsContainer) { $next += $item }
                    elseif ($item.Extension -eq '.json') {
                        try { $old = [IO.File]::ReadAllText($item.FullName) | ConvertFrom-Json -ErrorAction Stop }
                        catch { throw 'QUALIFICATION_REPORT_INVALID: review existing reports before proceeding.' }
                        if ($null -eq $old.actual_network_requests) { throw 'QUALIFICATION_REPORT_INVALID: stopped.' }
                        if ($old.actual_network_requests -gt 0) {
                            throw 'QUALIFICATION_ALREADY_RUN: existing real samples; inventory first, never restart this batch.'
                        }
                    }
                }
            }
            $directories = $next
        }
    }
    # Check all five plans before any network consent can start the schedule.
    foreach ($condition in $conditions) {
        $caseId = "$prefix-$condition"
        $manifest = "scripts/manifests/assistant-$caseId.json"
        if (-not (Test-Path -LiteralPath (Join-Path $root $manifest) -PathType Leaf) -or
                -not $ExpectedHashes.ContainsKey($caseId)) { throw 'QUALIFICATION_MANIFEST_MISSING: stopped.' }
        $preview = Invoke-QualificationProcess -Python $python -Manifest $manifest
        if ($preview.ExitCode -ne 0 -or $preview.Data.dry_run -ne $true -or
                $preview.Data.actual_network_requests -ne 0 -or
                $preview.Data.plan.case_id -ne $caseId -or
                $preview.Data.plan.plan_sha256 -ne $ExpectedHashes[$caseId]) {
            throw 'QUALIFICATION_PLAN_CHANGED: stopped before network; review preregistration.'
        }
    }
    $boundary = $root
    foreach ($part in @('outputs', 'assistant-qualification', 'cross-model', $ModelKey)) {
        $boundary = Join-Path $boundary $part
        Assert-QualificationPath $boundary
        if (-not (Test-Path -LiteralPath $boundary)) { New-Item -ItemType Directory -Path $boundary | Out-Null }
    }
    $schedule = Join-Path $reports 'run-order.txt'
    Assert-QualificationPath $schedule
    if (Test-Path -LiteralPath $schedule) {
        $saved = @([IO.File]::ReadAllLines($schedule))
        if (($saved -join ',') -cne ($order -join ',')) { throw 'QUALIFICATION_ORDER_CHANGED: stopped.' }
    } else {
        $file = [IO.File]::Open($schedule, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try {
            $writer = [IO.StreamWriter]::new($file, [Text.UTF8Encoding]::new($false))
            try { foreach ($caseId in $order) { $writer.WriteLine($caseId) }; $writer.Flush(); $file.Flush($true) }
            finally { $writer.Dispose() }
        } finally { $file.Dispose() }
    }
    if (-not $ConfirmNetwork) {
        Write-Host "$prefix PREPARED: 30 fixed runs / at most 60 requests; no Provider requests."
        return
    }
    Write-Host "$prefix REAL NETWORK REQUEST: fixed batch, retry=0; no extra samples."
    $hardStops = @('CREDENTIAL_FILE_ERROR', 'SECRET_MISSING', 'QUALIFICATION_UNSAFE_LOGGING',
        'QUALIFICATION_REPORT_ERROR', 'QUALIFICATION_IDENTITY_MISMATCH', 'USER_CANCELLED')
    $localTransportStops = @('CONNECT_TIMEOUT', 'READ_TIMEOUT', 'TOTAL_TIMEOUT', 'TIMEOUT',
        'CONNECTION_ERROR', 'DNS_ERROR', 'TLS_ERROR', 'PROXY_ERROR', 'SDK_ERROR', 'HTTP_502', 'HTTP_503', 'HTTP_504')
    $actualTotal = 0
    for ($index = 0; $index -lt $order.Count; $index++) {
        $caseId = $order[$index]
        $manifest = "scripts/manifests/assistant-$caseId.json"
        $preview = Invoke-QualificationProcess -Python $python -Manifest $manifest
        if ($preview.ExitCode -ne 0 -or $preview.Data.dry_run -ne $true -or
                $preview.Data.actual_network_requests -ne 0 -or
                $preview.Data.plan.plan_sha256 -ne $ExpectedHashes[$caseId]) {
            throw 'QUALIFICATION_PLAN_CHANGED: stop and review partial batch; do not restart.'
        }
        # One new Python process, one manifest; this function never retries.
        $run = Invoke-QualificationProcess -Python $python -Manifest $manifest -Network
        $summary = $run.Data
        if ($summary.error_code -in @('QUALIFICATION_REPORT_ERROR', 'QUALIFICATION_UNSAFE_LOGGING')) {
            throw 'QUALIFICATION_LOCAL_SAFETY_STOP: inspect safe records; do not restart.'
        }
        # CLI reports are relative to the workspace, not to the generated directory.
        $reportPrefix = '^outputs/assistant-qualification/cross-model/' + [regex]::Escape($ModelKey) + '/'
        if ($run.ExitCode -notin @(0, 1) -or $summary.report -isnot [string] -or
                $summary.report -notmatch $reportPrefix) {
            throw 'QUALIFICATION_CLI_REPORT_INVALID: stopped; do not restart.'
        }
        $reportPath = [IO.Path]::GetFullPath((Join-Path $root $summary.report))
        if (-not $reportPath.StartsWith($reports + [IO.Path]::DirectorySeparatorChar,
                [StringComparison]::OrdinalIgnoreCase)) { throw 'QUALIFICATION_REPORT_PATH_INVALID: stopped.' }
        $reportParent = $reportPath
        while (-not [string]::Equals($reportParent, $reports, [StringComparison]::OrdinalIgnoreCase)) {
            Assert-QualificationPath $reportParent
            $reportParent = Split-Path -Parent $reportParent
        }
        try { $safe = [IO.File]::ReadAllText($reportPath) | ConvertFrom-Json -ErrorAction Stop }
        catch { throw 'QUALIFICATION_REPORT_INVALID: stopped; do not restart.' }
        if ($safe.plan.plan_sha256 -ne $ExpectedHashes[$caseId] -or $safe.plan.case_id -ne $caseId -or
                $safe.run_id -ne $summary.run_id -or $safe.request_count -notin @(0, 1, 2) -or
                $safe.actual_network_requests -notin @(0, 1, 2) -or $safe.transport_attempts -notin @(0, 1, 2) -or
                $safe.actual_network_requests -ne $summary.actual_network_requests -or
                $safe.error_code -ne $summary.error_code) { throw 'QUALIFICATION_REPORT_IDENTITY_OR_BUDGET_INVALID: stopped.' }
        $actualTotal += $safe.actual_network_requests
        Write-Host "$($index + 1)/30 $caseId : $($safe.status) / $($safe.error_code) / requests=$($safe.actual_network_requests)"
        if ($safe.error_code -in $hardStops -or
                ($ModelKey -eq 'ollama' -and $safe.error_code -in $localTransportStops)) {
            throw 'QUALIFICATION_BATCH_STOPPED: local safety, cancellation or Local transport failure; inventory partial runs before continuing.'
        }
    }
    Write-Host "$prefix COMPLETED: 30 runs / $actualTotal requests; stop, no repeat or other model batch."
}
