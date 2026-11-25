@echo off
rem ONE-TIME: rebuilds the git history as one commit per phase (Phase 1..8), then force-pushes it to GitHub.
rem The old history is kept locally on the branch "backup-before-history".
cd /d "%~dp0"
set LOG=history_result.log
echo [%date% %time%] push_history.bat started> %LOG%
where git >nul 2>&1 || (echo Git is not installed.& pause& exit /b 1)
git branch -f backup-before-history main >> %LOG% 2>&1
git checkout --orphan rebuild >> %LOG% 2>&1
git rm -r -q --cached . >> %LOG% 2>&1

git add -- .gitignore .env.example requirements.txt pytest.ini plan_trip.bat run_tests.bat travel_planner/__init__.py travel_planner/__main__.py travel_planner/state.py travel_planner/config.py travel_planner/routing.py travel_planner/graph.py travel_planner/runner.py travel_planner/engine.py travel_planner/cli.py travel_planner/utils.py travel_planner/tools/__init__.py travel_planner/tools/catalog.py tests/conftest.py tests/test_config.py >> %LOG% 2>&1
git commit -q -m "Phase 1: skeleton - TripState, config, mock catalog, graph wiring, runner, CLI" >> %LOG% 2>&1

git add -- travel_planner/intake.py travel_planner/agents.py travel_planner/itinerary.py tests/test_destinations.py >> %LOG% 2>&1
git commit -q -m "Phase 2: core agents - intake, flight/hotel/weather/activities, merge, parallel fan-out" >> %LOG% 2>&1

git add -- travel_planner/deps.py tests/test_scenarios.py tests/test_graph_engine.py >> %LOG% 2>&1
git commit -q -m "Phase 3: control flow - budget retries, critic, supervisor strategies, scenario tests" >> %LOG% 2>&1

git add -- travel_planner/guardrails.py travel_planner/checks.py travel_planner/feedback.py travel_planner/store.py travel_planner/tools/errors.py travel_planner/tools/client.py tests/test_intake_guardrails.py tests/test_resilience.py >> %LOG% 2>&1
git commit -q -m "Phase 4: safety, human approval, checkpoints, retries and graceful degradation" >> %LOG% 2>&1

git add -- travel_planner/llm travel_planner/rag travel_planner/tools travel_planner/mcp_server.py tests/test_llm.py tests/test_mcp.py tests/test_tools_weather.py tests/test_places_sources.py >> %LOG% 2>&1
git reset -q -- travel_planner/tools/dining.py >> %LOG% 2>&1
git commit -q -m "Phase 5: LLM router, real data (Open-Meteo, OSM, Wikipedia, Wikivoyage), MCP server, any-destination support" >> %LOG% 2>&1

git add -- travel_planner/api.py travel_planner/service.py travel_planner/devserver.py travel_planner/static tests/test_api_cli.py run_server.bat diagnose.bat install_requirements.bat >> %LOG% 2>&1
git commit -q -m "Phase 6: FastAPI and single-page UI, Windows scripts" >> %LOG% 2>&1

git add -- evals travel_planner/trace.py tests/test_evals.py tests/test_trace.py run_evals.bat README.md docs >> %LOG% 2>&1
git commit -q -m "Phase 7: evals, tracing, README and docs" >> %LOG% 2>&1

git add -A >> %LOG% 2>&1
git commit -q -m "Phase 8: top sights, restaurant guide (veg / non-veg), GitHub push scripts" >> %LOG% 2>&1

git branch -M main >> %LOG% 2>&1
git push --force -u origin main >> %LOG% 2>&1
if errorlevel 1 (echo PUSH FAILED. See %LOG%.& echo history push failed>> %LOG%) else (echo Done: 8 phase commits pushed.& echo history ok>> %LOG%)
git log --oneline >> %LOG% 2>&1
pause
