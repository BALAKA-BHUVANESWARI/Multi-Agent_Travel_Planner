@echo off
rem Runs the full test suite.
cd /d "%~dp0..\backend"
python -m pytest
echo.
pause
