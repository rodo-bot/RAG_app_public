$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$runtime = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $runtime)) { $runtime = 'python' }
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { & $runtime -m venv --system-site-packages '.venv' }
& $python -m pip install --disable-pip-version-check -r 'requirements.txt'
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $python -c "from fastembed import TextEmbedding; from pathlib import Path; model=TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir=Path('models')); print('Local embedding dimensions:', len(next(model.embed(['ready']))))"
if ($LASTEXITCODE -ne 0) { throw 'Local embedding model setup failed.' }
Write-Host 'RAG Knowledge Base is ready.'
