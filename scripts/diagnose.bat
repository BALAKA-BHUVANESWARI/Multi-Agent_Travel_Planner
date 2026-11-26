@echo off
rem Writes a short report about this computer's setup to .runtime\diagnose.txt (no keys or other secrets).
cd /d "%~dp0.."
if not exist .runtime mkdir .runtime
call :report > .runtime\diagnose.txt 2>&1
echo Done. Report saved to .runtime\diagnose.txt
timeout /t 3 >nul
goto :eof

:report
echo === python on PATH ===
where python
python --version
python -m pip --version
echo.
echo === node and npm ===
call node --version
call npm --version
echo.
echo === key packages ===
python -m pip list 2>nul | findstr /i /r "^langgraph ^langchain ^jsonpatch ^fastapi ^uvicorn ^mcp ^pytest ^pydantic ^httpx"
echo.
echo === import checks ===
pushd backend
python -c "import jsonpatch; print('jsonpatch OK', jsonpatch.__version__)"
python -c "import langgraph.graph; print('langgraph.graph OK')"
python -c "from app.graph.engine import graph_self_check; print(graph_self_check())"
popd
echo.
echo === web page built? ===
if exist frontend\dist\index.html (echo yes) else (echo no: run scripts\install_requirements.bat)
echo.
echo === who listens on port 8000 ===
netstat -ano | findstr ":8000"
echo.
echo === python processes: id, parent id, command line ===
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' } | ForEach-Object { 'PID ' + $_.ProcessId + '  parent ' + $_.ParentProcessId + '  ' + $_.CommandLine }"
echo.
echo === elevated? ===
net session >nul 2>&1 && (echo running as administrator) || (echo not administrator)
exit /b
