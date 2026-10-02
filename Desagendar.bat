@echo off
chcp 65001 >nul
title Radar de Concursos - remover agendamento
schtasks /Delete /F /TN "Radar de Concursos"
echo.
pause
