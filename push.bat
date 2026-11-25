@echo off
rem Pushes the current project to GitHub. Double-click after each phase, or run: push.bat "Phase 8: message"
cd /d "%~dp0"
set REPO=https://github.com/BALAKA-BHUVANESWARI/Multi-Agent_Travel_Planner.git
set LOG=push_result.log
echo [%date% %time%] push.bat started> %LOG%
where git >nul 2>&1 || (echo Git is not installed. Install it from https://git-scm.com and run this again.& echo git missing>> %LOG%& pause& exit /b 1)
if not exist .git (
  git init >> %LOG% 2>&1
  git branch -M main >> %LOG% 2>&1
)
git remote get-url origin >nul 2>&1 || git remote add origin %REPO%
rem Safety: never commit secrets or local data.
git rm -r --cached --ignore-unmatch .env travel_planner.db* traces.jsonl .place_cache >> %LOG% 2>&1
set MSG=%~1
if "%MSG%"=="" if exist phase_message.txt set /p MSG=<phase_message.txt
if "%MSG%"=="" set MSG=Update travel planner (%date% %time%)
git add -A >> %LOG% 2>&1
git commit -m "%MSG%" >> %LOG% 2>&1
git pull origin main --rebase --allow-unrelated-histories >> %LOG% 2>&1
git push -u origin main >> %LOG% 2>&1
if errorlevel 1 (echo PUSH FAILED. See %LOG%.& echo push failed>> %LOG%) else (echo Pushed to %REPO%& echo push ok>> %LOG%)
pause
