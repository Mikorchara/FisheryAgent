[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$RunDirectory, [switch]$BotOnly)
$ErrorActionPreference='Stop'
$taskRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$taskPython = Join-Path $taskRoot '.venv/Scripts/python.exe'
$taskArgs=@('-X','utf8','-I','-B',(Join-Path $PSScriptRoot 'prototype_stack.py'),'--stop-directory',$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($RunDirectory))
if ($BotOnly) { $taskArgs+='--stop-bot' }
& $taskPython @taskArgs
if ($LASTEXITCODE -ne 0) { throw "PROTOTYPE_STACK_COMMAND_FAILED ($LASTEXITCODE)" }
