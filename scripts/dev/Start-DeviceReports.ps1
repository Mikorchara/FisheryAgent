[CmdletBinding()]
param([string]$Directory, [string]$DeviceId='fish-monitor-orin-01',
      [string]$Bind='127.0.0.1', [int]$Port=8780,
      [switch]$Check,[switch]$InitStore,[switch]$Serve)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if (([int]$Check.IsPresent+[int]$InitStore.IsPresent+[int]$Serve.IsPresent) -gt 1) { throw 'DEVICE_REPORT_ACTION_CONFLICT' }
$taskRoot=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$taskPython=Join-Path $taskRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) { throw 'LOCAL_VENV_REQUIRED' }
if (-not $Directory) { $Directory=Join-Path $taskRoot 'apps/data/device-reports' }
$taskDirectory=$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Directory)
$taskArgs=@('-X','utf8','-I','-B',(Join-Path $PSScriptRoot 'device_report_cli.py'),'--directory',$taskDirectory,'--device-id',$DeviceId,'--bind',$Bind,'--port',"$Port")
if ($InitStore) { $taskArgs+='--init-store' }
elseif ($Serve) { $taskArgs+='--serve' }
else { $taskArgs+='--check' }
$previousToken=$null
try {
    if ($Serve) {
        $previousToken=[Environment]::GetEnvironmentVariable('FISHERY_DEVICE_REPORT_TOKEN','Process')
        $secret=Read-Host '输入与开发板约定的设备令牌（32–128位字母数字，不回显）' -AsSecureString
        $pointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
        try { $env:FISHERY_DEVICE_REPORT_TOKEN=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer);$secret.Dispose() }
    }
    Push-Location -LiteralPath $taskRoot
    try { & $taskPython @taskArgs; $resultCode=$LASTEXITCODE }
    finally { Pop-Location }
    if ($resultCode -ne 0) { throw "DEVICE_REPORT_COMMAND_FAILED ($resultCode)" }
}
finally {
    if ($Serve) { [Environment]::SetEnvironmentVariable('FISHERY_DEVICE_REPORT_TOKEN',$previousToken,'Process') }
}
