@echo off
rem Writes a short report about this computer's Python setup and port 8000 to diagnose.txt (no secrets).
cd /d "%~dp0"
(
echo === python on PATH ===
where python
python --version
python -m pip --version
echo.
echo === key packages ===
python -m pip list 2>nul | findstr /i /r "^langgraph ^langchain ^jsonpatch ^fastapi ^uvicorn ^mcp ^pytest ^pydantic ^httpx"
echo.
echo === import checks ===
python -c "import jsonpatch; print('jsonpatch OK', jsonpatch.__version__)" 2>&1
python -c "import langchain_core; print('langchain_core', langchain_core.__version__)" 2>&1
python -c "import langgraph.graph; print('langgraph.graph OK')" 2>&1
python -c "from travel_planner.engine import graph_self_check; print(graph_self_check())" 2>&1
echo.
echo === who listens on port 8000 ===
netstat -ano | findstr ":8000"
echo.
echo === python processes (id, parent id, command line) ===
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' } | ForEach-Object { 'PID ' + $_.ProcessId + '  parent ' + $_.ParentProcessId + '  ' + $_.CommandLine }"
echo.
echo === elevated? ===
net session >nul 2>&1 && (echo running as administrator) || (echo not administrator)
) > diagnose.txt 2>&1
echo Done. Report saved to diagnose.txt
timeout /t 3 >nul
