@echo off
chcp 65001 >nul
title Selecionar grupo de ofertas
cd /d "%~dp0"
".venv\Scripts\python.exe" main.py --choose-group
pause
