@echo off
rem Double-click to open SinhalaSubs (until Phase 6 makes a real .exe).
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m sinhalasubs
