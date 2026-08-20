@echo off
rem build_exe.bat - Build standalone TeamsMonitor.exe using PyInstaller
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" build_exe.py %*
) else (
    python build_exe.py %*
)
