[CmdletBinding()]
param([string]$RequestFile, [string]$DataRoot, [int]$Port=8766,
      [string]$Scenario='normal', [int]$Seed=42, [switch]$WithBot, [switch]$BotOnly,
      [switch]$Check, [switch]$PrepareDemo, [switch]$InteractiveScenario,
      [switch]$OpenBrowser, [switch]$NoAssistant, [int]$RunSeconds=1800)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$taskRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$taskPython = Join-Path $taskRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) { throw 'LOCAL_VENV_REQUIRED' }
$taskArgs=@('-X','utf8','-I','-B',(Join-Path $PSScriptRoot 'prototype_stack.py'),'--port',"$Port",'--scenario',$Scenario,'--seed',"$Seed",'--seconds',"$RunSeconds")
if ($RequestFile) { $taskArgs+=@('--request-file',$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($RequestFile)) }
if ($DataRoot) { $taskArgs+=@('--data-root',$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($DataRoot)) }
if ($NoAssistant) { $taskArgs+='--no-assistant' }
foreach ($item in @(@($WithBot,'--with-bot'),@($BotOnly,'--bot-only'),@($Check,'--check'),@($PrepareDemo,'--prepare-demo'),@($InteractiveScenario,'--interactive-scenario'),@($OpenBrowser,'--open-browser'))) {
    if ($item[0]) { $taskArgs+=$item[1] }
}
& $taskPython @taskArgs
if ($LASTEXITCODE -ne 0) { throw "PROTOTYPE_STACK_COMMAND_FAILED ($LASTEXITCODE)" }
