# Create the SEPARATE training environment (home PC, Windows).
# The app venv (.venv) is never touched; training deps stay out of the
# shipped application.
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $RepoRoot

if (-not (Test-Path ".venv-training\Scripts\python.exe")) {
    python -m venv .venv-training
}
& .\.venv-training\Scripts\python.exe -m pip install --upgrade pip
# PyTorch with CUDA 12.4 wheels (RTX 4060 Ti / Ada).
& .\.venv-training\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cu124
& .\.venv-training\Scripts\python.exe -m pip install -r requirements-training.txt
Write-Host "Training env ready. Next:"
Write-Host "  .\.venv-training\Scripts\python.exe -m neuralcut.training.train_qlora --preflight"
