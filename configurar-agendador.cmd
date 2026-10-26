@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Configurar agendador - Promos Gamer
".venv\Scripts\python.exe" configurar-agendador.py
pause
