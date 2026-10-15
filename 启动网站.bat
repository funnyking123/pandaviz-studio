@echo off
chcp 65001 >nul
title PandasViz Studio - visual pandas analytics workbench
cd /d "%~dp0"

echo ============================================================
echo   PandasViz Studio is starting ...
echo.
echo   The browser will open http://127.0.0.1:5000 automatically.
echo   KEEP THIS WINDOW OPEN while you use the site.
echo   To stop the server: press Ctrl+C or just close this window.
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 goto nopython

python -c "import pandas, flask" >nul 2>nul
if errorlevel 1 (
  echo [!] pandas / flask not found - installing requirements.txt now ...
  python -m pip install -r requirements.txt
  echo.
)

set PYTHONIOENCODING=utf-8
python run.py --port 5000

echo.
echo Server stopped. Press any key to close this window.
pause >nul
exit /b 0

:nopython
echo [!] python command not found.
echo     Please install Python 3 and tick "Add python.exe to PATH":
echo     https://www.python.org/downloads/
echo.
pause
exit /b 1
