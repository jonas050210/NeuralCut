# Build the NeuralCut backend sidecar for the Tauri installer (Windows).
# Requires: scripts/setup.ps1 already run (.venv with dependencies).
# Output: src-tauri/binaries/neuralcut-backend-x86_64-pc-windows-msvc.exe
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $RepoRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Virtual environment not found. Run .\scripts\setup.ps1 first."
}
& .\.venv\Scripts\python.exe -m pip install pyinstaller
# PyInstaller entry point: neuralcut/__main__.py delegates to main().
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile `
    --name neuralcut-backend `
    --add-data "$RepoRoot\neuralcut\frontend;neuralcut/frontend" `
    --distpath build\sidecar-dist --workpath build\sidecar-work `
    --specpath build `
    neuralcut\__main__.py
$Target = "src-tauri\binaries\neuralcut-backend-x86_64-pc-windows-msvc.exe"
New-Item -ItemType Directory -Force -Path "src-tauri\binaries" | Out-Null
Copy-Item "build\sidecar-dist\neuralcut-backend.exe" $Target -Force
Write-Host "Sidecar written to $Target"
Write-Host "Smoke test: & $Target --no-browser --port 8899  (then Ctrl+C)"
Write-Host "Optional: copy an LGPL-configured ffmpeg.exe next to the shell via the installer resources; see docs\PACKAGING.md."
