@echo off
chcp 65001 >nul
title Radar de Concursos - agendamento
cd /d "%~dp0"
echo Agendando o rastreio para rodar de segunda a sexta, as 07:00.
echo.
schtasks /Create /F /TN "Radar de Concursos" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 07:00 ^
  /TR "pythonw \"%~dp0app.py\" rastrear"
if %errorlevel%==0 (
  echo.
  echo Pronto. O radar vai varrer as fontes sozinho todo dia util as 07:00.
  echo Para desligar, rode "Desagendar.bat".
) else (
  echo.
  echo Nao consegui agendar. Tente abrir este arquivo como administrador.
)
echo.
pause
