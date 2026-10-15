@echo off
chcp 65001 >nul
title PandasViz Studio - rebuild docs and package
cd /d "%~dp0"

echo ============================================================
echo   Rebuild the Word docs (docs\*.docx) from the .md files
echo   and repackage pandas-viz-studio-网站源代码.zip
echo.
echo   IMPORTANT: close any .docx opened in Word / WPS first,
echo   otherwise that file will be skipped (it is locked).
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 goto nopython

python tools\make_docs.py
echo.
python tools\build_zip.py
echo.
echo Finished. Press any key to close this window.
pause >nul
exit /b 0

:nopython
echo [!] python command not found.
echo     Please install Python 3 and tick "Add python.exe to PATH":
echo     https://www.python.org/downloads/
echo.
pause
exit /b 1
