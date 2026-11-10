@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto nosetup
echo Starting Job Hunter. Your browser will open. Close this window to stop it.
".venv\Scripts\python.exe" -m streamlit run dashboard\app.py
pause
exit /b 0

:nosetup
echo Run setup.bat first.
pause
exit /b 1
