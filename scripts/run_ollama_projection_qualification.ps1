# Qualification preparation only. Without -ConfirmNetwork: dry-run plans + fixed order.
# Same H2F / H2 A-B / H5 A-B experiment as the completed DeepSeek batch.
# Prepared for explicit user execution; preparation never contacts Ollama.
# Local target: ollama-qwen35-4b-r1, Thinking OFF / Normal, Auth NONE.
# 30 independent runs, <=60 requests, <=256 output tokens/request, retry=0.
# Existing real reports block restart; a stopped batch must be audited first.
[CmdletBinding()]
param([switch]$ConfirmNetwork)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'projection_qualification_runner.ps1')
$hashes = @{
    'OLLAMA-H2-A' = '62ce494f4545dcc1db4e22869b1732c3bfd1b92f5a66f2099a3d32e5931b77c3'
    'OLLAMA-H2-B' = '689c61641a5e328c1fd71abb632d83c7b03ffec09f7394dfeb7060317babcc64'
    'OLLAMA-H2F' = '1aaa4f5c3a4dd99a88454e624e1636b7cd84d14c9ae2cc630cc29c0e4c2dd962'
    'OLLAMA-H5-A' = 'c39308f665d5088504c62c9bb16faa01f1612629d1b888f542adbc7f95b296c5'
    'OLLAMA-H5-B' = '9ad18a05f9dfa81fc977c4ea8f4ce5569843ebb45482ee95aaad4368a2e212ab'
}
Invoke-ProjectionQualificationBatch -ModelKey 'ollama' -ExpectedHashes $hashes `
    -ProjectRoot (Split-Path -Parent $PSScriptRoot) -ConfirmNetwork:$ConfirmNetwork
