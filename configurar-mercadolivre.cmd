@echo off
chcp 65001 >nul
title Configurar Mercado Livre - Promos Gamer
cd /d "%~dp0"
".venv\Scripts\python.exe" -X utf8 configurar-mercadolivre.py
pause
