@echo off
rem NEXO: doble clic para preparar y arrancar. Ejecuta iniciar.ps1 sin cambiar la configuracion de Windows.
title NEXO
cd /d "%~dp0"
echo No cierres esta ventana mientras uses NEXO: cerrarla apaga NEXO.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0iniciar.ps1" %*
if errorlevel 1 pause
