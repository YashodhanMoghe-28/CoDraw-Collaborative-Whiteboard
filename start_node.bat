@echo off
cd /d "%~dp0"
if "%~2"=="" (
 echo Usage: start_node.bat ID YOUR_LAN_IP [PORT] [OTHER_LAPTOP_IP]
 echo Example: start_node.bat 3 192.168.1.13 8765 192.168.1.12
 echo Or double-click start_lan.bat for guided setup.
 pause
 exit /b 1
)
set "NODE_PORT=%~3"
if "%NODE_PORT%"=="" set "NODE_PORT=8765"
set "SEED_OPTION="
if not "%~4"=="" set "SEED_OPTION=--seed http://%~4:8765"
.venv\Scripts\python.exe -u server.py --id %1 --advertise %2 --interface %2 --port %NODE_PORT% --console --demo-controls %SEED_OPTION%
pause
