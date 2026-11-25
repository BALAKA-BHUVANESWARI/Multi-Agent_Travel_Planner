@echo off
rem Runs the eval set (23 prompts, graph vs single-agent baseline) and, with your keys in .env, the LLM judge.
rem Writes evals\report.md. Uses a few free-tier LLM calls for the judge only.
cd /d "%~dp0"
python evals\run_evals.py --judge
echo.
echo Report written to evals\report.md
pause
