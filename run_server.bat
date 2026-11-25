@echo off
rem Starts the travel planner (API + UI) and opens the browser.
cd /d "%~dp0"
set PORT=8000
set LOG=server_restart.log
echo [%date% %time%] run_server.bat started> %LOG%
rem Stop any older copy still listening on the port, so a restart always loads the latest .env and code.
call :freeport %PORT%
if defined BUSY (
  echo Port %PORT% is still in use by another program ^(details in %LOG%^). Using port 8001 instead.
  set PORT=8001
  call :freeport 8001
)
echo Starting Travel Planner on http://127.0.0.1:%PORT%  (Ctrl+C to stop)
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:%PORT%"
python -m uvicorn travel_planner.api:create_app --factory --port %PORT%
echo.
echo Server stopped. If you saw an error above, note it down.
pause
goto :eof

:freeport
set BUSY=
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":%1 .*LISTENING"') do (
  echo Stopping process %%p that is using port %1>> %LOG%
  taskkill /f /t /pid %%p >> %LOG% 2>&1
)
timeout /t 2 /nobreak >nul
netstat -ano | findstr /r /c:":%1 .*LISTENING" >nul && set BUSY=1
exit /b
