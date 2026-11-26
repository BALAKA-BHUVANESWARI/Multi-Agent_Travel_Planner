@echo off
rem Commits everything and pushes to GitHub.
rem   scripts\push.bat                   uses phase_message.txt as the commit message
rem   scripts\push.bat "Your message"    uses your own message
cd /d "%~dp0.."
if not exist .runtime mkdir .runtime
set "LOG=%CD%\.runtime\push_result.log"
set REPO=https://github.com/BALAKA-BHUVANESWARI/Multi-Agent_Travel_Planner.git
echo [%date% %time%] push.bat started> "%LOG%"
where git >nul 2>&1 || (echo Git is not installed. Install it from https://git-scm.com and run this again.& pause& exit /b 1)
if not exist .git (
  git init >> "%LOG%" 2>&1
  git branch -M main >> "%LOG%" 2>&1
)
git remote get-url origin >nul 2>&1 || git remote add origin %REPO%
rem Safety: never commit secrets or local data.
git rm -r -q --cached --ignore-unmatch .env .runtime travel_planner.db travel_planner.db.graph traces.jsonl .place_cache >> "%LOG%" 2>&1
git add -A >> "%LOG%" 2>&1
if not "%~1"=="" (
  git commit -m "%~1" >> "%LOG%" 2>&1
) else if exist phase_message.txt (
  git commit -F phase_message.txt >> "%LOG%" 2>&1
) else (
  git commit -m "Update travel planner" >> "%LOG%" 2>&1
)
git pull origin main --rebase >> "%LOG%" 2>&1
git push -u origin main >> "%LOG%" 2>&1
if errorlevel 1 (echo PUSH FAILED. See %LOG%& echo push failed>> "%LOG%") else (echo Pushed to %REPO%& echo push ok>> "%LOG%")
pause
