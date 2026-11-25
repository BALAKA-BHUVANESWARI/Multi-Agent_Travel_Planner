@echo off
rem Installs the Python packages the planner needs (the same list as requirements.txt).
cd /d "%~dp0"
python -m pip install -r requirements.txt
echo.
echo Finished. If there are no red error lines above, close this window and double-click run_server.bat.
pause
