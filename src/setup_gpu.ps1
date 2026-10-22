$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$runtime = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $runtime)) { $runtime = 'python' }
$gpuVenv = Join-Path $PSScriptRoot 'gpu-venv'
$python = Join-Path $gpuVenv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    & $runtime -m venv $gpuVenv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the GPU environment.' }
}
& $python -m pip install --disable-pip-version-check -r 'requirements-gpu.txt'
if ($LASTEXITCODE -ne 0) { throw 'GPU dependency installation failed.' }
& $python 'tools\check_gpu.py'
if ($LASTEXITCODE -ne 0) { throw 'CUDA did not activate. The CPU app is unchanged.' }
$shortcutPath = Join-Path $PSScriptRoot 'RAG Knowledge Base GPU.lnk'
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $gpuVenv 'Scripts\pythonw.exe'
$shortcut.Arguments = '"' + (Join-Path $PSScriptRoot 'RAG Knowledge Base Desktop.pyw') + '"'
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.IconLocation = Join-Path $PSScriptRoot 'RAG Knowledge Base.exe'
$shortcut.Save()
Write-Host 'GPU embedding is ready. Open RAG Knowledge Base GPU.lnk after closing the old app.'
