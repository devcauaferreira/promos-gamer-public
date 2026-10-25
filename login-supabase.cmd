@echo off
chcp 65001 >nul
title Login Supabase - Promos Gamer
cd /d "%~dp0"
echo Abrindo o login oficial do Supabase em modo interativo.
echo Conclua a autorizacao no navegador e siga as instrucoes desta janela.
echo Nao envie tokens ou codigos pelo chat.
call npx.cmd --yes supabase@2.122.0 --agent no --output-format text login --name promos-gamer
if errorlevel 1 (
  echo.
  echo O login nao foi concluido. Mantenha esta janela aberta para conferir o erro.
)
pause
