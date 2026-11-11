@echo off
setlocal
title Jarvis Launcher
cd /d "%~dp0"
rem  start_jarvis.bat            normal start
rem  start_jarvis.bat console    visible console for debugging
set "ARGS="
if /i "%~1"=="console" set "ARGS=-Console"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1" %ARGS%
if errorlevel 1 (
  echo.
  echo Something went wrong. Details: %LOCALAPPDATA%\JarvisAI\logs\setup.log
  pause
  exit /b 1
)
exit /b 0
