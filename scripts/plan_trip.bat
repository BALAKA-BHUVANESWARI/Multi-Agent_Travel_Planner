@echo off
rem Command-line planner: type a trip request, then approve, request changes or cancel.
cd /d "%~dp0..\backend"
set /p REQ=Describe your trip: 
python -m app "%REQ%"
echo.
pause
