@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo NeuralCut is not set up yet.
  echo Open PowerShell in this folder and run: .\scripts\setup.ps1
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m neuralcut %*
