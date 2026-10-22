$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$server = Join-Path $PSScriptRoot 'RAG Knowledge Base MCP.exe'
if (Test-Path -LiteralPath $server) {
    & $server
} else {
    & (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') -m ragkb.mcp_entry
}
