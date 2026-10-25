@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" main.py --watch --send
pause
