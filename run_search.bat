@echo off
rem Runs one search and writes the result to logs\search.log. Use this in Task Scheduler.
cd /d "%~dp0"
if not exist logs mkdir logs
if not exist ".venv\Scripts\python.exe" exit /b 1
echo ===== %date% %time% ===== >> logs\search.log
".venv\Scripts\python.exe" -m jobhunter.search >> logs\search.log 2>&1
".venv\Scripts\python.exe" -m jobhunter.backup >> logs\search.log 2>&1
exit /b 0
