@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Pasang Python 3.13 dari python.org dengan Tcl/Tk dan Python Launcher.
  echo Alternatif PowerShell: winget install -e --id Python.Python.3.13 --source winget
  pause
  exit /b 1
)
py -3 windows_runtime.py install
set "AFZAL_INSTALL_EXIT=%ERRORLEVEL%"
pause
exit /b %AFZAL_INSTALL_EXIT%
