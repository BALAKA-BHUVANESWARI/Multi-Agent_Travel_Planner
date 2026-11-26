@echo off
rem One-time setup: installs the Python packages and builds the web page. Needs Python and Node.js 18 or newer.
cd /d "%~dp0.."
python -m pip install -r backend\requirements.txt || goto :failed
where npm >nul 2>&1 || (echo Node.js is not installed. Get the LTS version from https://nodejs.org and run this again.& goto :failed)
cd frontend
call npm install || goto :failed
call npm run build || goto :failed
echo.
echo Finished. Start the planner with scripts\run_server.bat
pause
exit /b 0
:failed
echo.
echo Setup did not finish. Keep the error lines above if you need help.
pause
exit /b 1
