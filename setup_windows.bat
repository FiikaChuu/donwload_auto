@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python belum terpasang. Install Python 3.11+ dari python.org dengan Tcl/Tk dan Python Launcher.
  pause
  exit /b 1
)
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"
if errorlevel 1 (
  echo Aplikasi membutuhkan Python 3.11 atau lebih baru.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto :failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto :failed
echo Selesai. Buka jalankan_windows.bat untuk menjalankan aplikasi.
pause
exit /b 0
:failed
echo Instalasi gagal. Periksa pesan di atas dan koneksi internet, lalu jalankan ulang.
pause
exit /b 1
