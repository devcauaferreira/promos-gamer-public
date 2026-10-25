@echo off
chcp 65001 >nul
title Conectar WhatsApp - Promos Gamer
cd /d "%~dp0"
echo Iniciando WhatsApp. Aguarde o QR Code aparecer na janela do navegador.
node publishers/whatsapp_bridge.cjs
pause
