@echo off
rem Runs the eval set (multi-agent graph against a single-agent baseline) and, with your keys in .env, the LLM judge.
rem Writes backend\evals\report.md. Uses a few free-tier LLM calls for the judge only.
cd /d "%~dp0..\backend"
python evals\run_evals.py --judge
echo.
echo Report written to backend\evals\report.md
pause
