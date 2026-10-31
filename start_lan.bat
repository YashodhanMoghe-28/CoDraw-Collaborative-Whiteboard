@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
 echo First run setup_windows.bat on this laptop.
 pause
 exit /b 1
)
.venv\Scripts\python.exe -u lan.py %*
echo.
echo Server stopped. Run this file again to rejoin with the same log.
pause
