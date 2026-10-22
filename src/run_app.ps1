$ErrorActionPreference = 'Stop'
$gpuPythonw = Join-Path $PSScriptRoot 'gpu-venv\Scripts\pythonw.exe'
if (Test-Path -LiteralPath $gpuPythonw) {
    $entry = Join-Path $PSScriptRoot 'RAG Knowledge Base Desktop.pyw'
    Start-Process -FilePath $gpuPythonw -ArgumentList ('"' + $entry + '"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
    exit 0
}
$updatedCpu = Join-Path $PSScriptRoot 'RAG Knowledge Base CPU.exe'
if (Test-Path -LiteralPath $updatedCpu) {
    Start-Process -FilePath $updatedCpu -WindowStyle Hidden
    exit 0
}
$app = Join-Path $PSScriptRoot 'RAG Knowledge Base.exe'
if (Test-Path -LiteralPath $app) {
    Start-Process -FilePath $app -WindowStyle Hidden
    exit 0
}
Set-Location -LiteralPath $PSScriptRoot
& (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') -m ragkb web --open
