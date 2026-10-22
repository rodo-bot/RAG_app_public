$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run setup first to create .venv.' }
& $python -c 'import PyInstaller' 2>$null
if ($LASTEXITCODE -ne 0) { & $python -m pip install --disable-pip-version-check pyinstaller }
$work = Join-Path $env:TEMP 'RAGKnowledgeBase-PyInstaller'
$dist = Join-Path $PSScriptRoot 'dist'
& $python -m PyInstaller --noconfirm --onefile --windowed --collect-binaries sqlite_vec --name 'RAG Knowledge Base' --workpath (Join-Path $work 'desktop') --distpath $dist 'RAG Knowledge Base Desktop.pyw'
if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed.' }
& $python -m PyInstaller --noconfirm --onefile --console --collect-binaries sqlite_vec --name 'RAG Knowledge Base MCP' --workpath (Join-Path $work 'mcp') --distpath $dist 'RAG Knowledge Base MCP.py'
if ($LASTEXITCODE -ne 0) { throw 'MCP build failed.' }
if (Get-Process 'RAG Knowledge Base' -ErrorAction SilentlyContinue) { throw 'Close the RAG desktop app before replacing it.' }
Copy-Item -LiteralPath (Join-Path $dist 'RAG Knowledge Base.exe') -Destination (Join-Path $PSScriptRoot 'RAG Knowledge Base.exe') -Force
Copy-Item -LiteralPath (Join-Path $dist 'RAG Knowledge Base MCP.exe') -Destination (Join-Path $PSScriptRoot 'RAG Knowledge Base MCP.exe') -Force
Write-Host 'Built the RAG desktop app and MCP server.'
