@echo off
title Bots Control

set "SCRIPT_DIR=%~dp0"

:menu
cls
echo ======================================
echo            Bots Control
echo ======================================
echo   1. Start all bots
echo   2. Stop all bots
echo   3. Check status
echo   4. Restart all bots
echo   0. Exit
echo ======================================
set /p choice="Choose action (0-4): "

if "%choice%"=="1" powershell -ExecutionPolicy Bypass -File "%SCRIPT_DIR%bots.ps1" start
if "%choice%"=="2" powershell -ExecutionPolicy Bypass -File "%SCRIPT_DIR%bots.ps1" stop
if "%choice%"=="3" powershell -ExecutionPolicy Bypass -File "%SCRIPT_DIR%bots.ps1" status
if "%choice%"=="4" powershell -ExecutionPolicy Bypass -File "%SCRIPT_DIR%bots.ps1" restart
if "%choice%"=="0" exit

echo.
pause
goto menu