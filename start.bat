@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto nosetup
echo Starting Job Hunter. Your browser will open. Close this window to stop it.
rem 127.0.0.1 = only this PC can open the dashboard (your data stays private)
".venv\Scripts\python.exe" -m streamlit run dashboard\app.py --server.address 127.0.0.1
pause
exit /b 0

:nosetup
echo Run setup.bat first.
pause
exit /b 1
