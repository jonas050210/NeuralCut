$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $RepoRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python was not found on PATH. Install Python 3.10+ from https://www.python.org/ and reopen PowerShell."
}

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 'Python 3.10+ is required')"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host "NeuralCut setup complete."
Write-Host "Run: .\scripts\run.ps1"
Write-Host "Test: .\scripts\test.ps1"
