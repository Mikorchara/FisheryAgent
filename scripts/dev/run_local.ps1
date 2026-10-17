param(
    [ValidateSet('normal','low_oxygen','suspected_disease','reduced_feeding','combined_anomaly','device_offline')]
    [string]$Scenario = 'normal',
    [ValidateRange(1,65535)][int]$Port = 8766,
    [int]$Seed = 42,
    [switch]$NoAssistant,
    [switch]$NoStreaming,
    [switch]$NoMultiRound,
    [switch]$NoHistory
)
$ErrorActionPreference = 'Stop'
$workspaceRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$pythonPath = Join-Path $workspaceRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) { throw 'LOCAL_VENV_REQUIRED' }
$launchArgs = @((Join-Path $PSScriptRoot 'local_session.py'),'--scenario',$Scenario,'--port',"$Port",'--seed',"$Seed")
if ($NoAssistant) { $launchArgs += '--no-assistant' }
if ($NoStreaming) { $launchArgs += '--no-streaming' }
if ($NoMultiRound) { $launchArgs += '--no-multi-round' }
if ($NoHistory) { $launchArgs += '--no-history' }
# Approved Qwen unified trial follows History/transport switches in the supervisor.
# Foreground supervisor owns only its two children; no Provider call on startup.
& $pythonPath @launchArgs
exit $LASTEXITCODE
