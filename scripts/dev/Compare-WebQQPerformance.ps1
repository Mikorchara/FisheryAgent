#requires -Version 7.0
[CmdletBinding()]
param(
    [switch]$Smoke,
    [switch]$Benchmark,
    [ValidateSet('Both','Core','Entry')][string]$Suite = 'Both',
    [ValidateRange(30,300)][int]$Samples = 30,
    [ValidateRange(1,5)][int]$Warmup = 2,
    [string]$OutputRoot
)
$ErrorActionPreference = 'Stop'
if ($Smoke -and $Benchmark) { throw 'Smoke 与 Benchmark 不能同时指定。' }
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$python = Join-Path $root '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw '找不到项目虚拟环境。' }
$driver = Join-Path $PSScriptRoot 'compare_webqq_performance.py'
$mode = if ($Benchmark) { 'benchmark' } else { 'smoke' }
$arguments = @('-X','utf8','-I','-B',$driver,'--mode',$mode,'--suite',$Suite.ToLowerInvariant(),
    '--samples',"$Samples",'--warmup',"$Warmup")
if ($OutputRoot) { $arguments += @('--output-root',[IO.Path]::GetFullPath($OutputRoot)) }
Write-Host '仅离线：合成 Monitoring、Mock SDK/QQ；不会读取真实凭据或连接服务。'
Write-Host ('模式：' + $mode + '；完整基准可能需要十几分钟，期间会逐组显示进度。')
$pushed = $false
try {
    Push-Location -LiteralPath $root; $pushed = $true
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw '性能实验未全部通过；请保留已生成的报告，不自动重跑失败样本。' }
} finally {
    if ($pushed) { Pop-Location }
}
