@echo off
rem Convenience launcher: runs the bash build in Git Bash.
set "GB=%ProgramFiles%\Git\bin\bash.exe"
if not exist "%GB%" (echo Git for Windows is required: https://git-scm.com & exit /b 1)
"%GB%" -lc "cd '%~dp0' && ./jarvis.sh %*"
