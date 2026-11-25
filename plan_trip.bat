@echo off
rem Interactive CLI planner (type a trip request, then approve / request changes / cancel).
cd /d "%~dp0"
set /p REQ=Describe your trip: 
python -m travel_planner "%REQ%"
echo.
pause
