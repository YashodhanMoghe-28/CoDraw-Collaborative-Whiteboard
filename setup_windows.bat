@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (python -m venv .venv) else (py -3 -m venv .venv)
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail
echo Setup complete. Run start_lan.bat on each laptop.
pause
exit /b 0
:fail
echo Setup failed. Install Python 3.11 or newer and check the error above.
pause
exit /b 1
