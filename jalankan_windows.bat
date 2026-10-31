@echo off
setlocal
cd /d "%~dp0"
if not exist ".afzal-runtime.json" (
  echo Jalankan setup_windows.bat terlebih dahulu.
  pause
  exit /b 1
)
py -3 windows_runtime.py run
set "AFZAL_RUN_EXIT=%ERRORLEVEL%"
if not "%AFZAL_RUN_EXIT%"=="0" pause
exit /b %AFZAL_RUN_EXIT%
