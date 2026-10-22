$ErrorActionPreference = 'Stop'
$pythonw = Join-Path $env:LOCALAPPDATA 'RAGKnowledgeBase\gpu-venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) { throw 'Run setup_gpu.ps1 first.' }
$entry = Join-Path $PSScriptRoot 'RAG Knowledge Base Desktop.pyw'
Start-Process -FilePath $pythonw -ArgumentList ('"' + $entry + '"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
