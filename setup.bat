@echo off
cd /d "%~dp0"
echo === Job Hunter setup ===

where py >nul 2>nul
if errorlevel 1 goto nopython

if not exist ".venv\Scripts\python.exe" py -m venv .venv
if not exist ".venv\Scripts\python.exe" goto novenv

".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto pipfail

if not exist ".env" copy ".env.example" ".env" >nul

rem Stop Streamlit from asking for an email on first run
if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  >"%USERPROFILE%\.streamlit\credentials.toml" echo [general]
  >>"%USERPROFILE%\.streamlit\credentials.toml" echo email = ""
)

".venv\Scripts\python.exe" -c "from jobhunter import db, config; config.ensure_dirs(); db.init_db(); print('Database ready.')"
echo.
echo Setup finished. Double-click start.bat to open the dashboard.
pause
exit /b 0

:nopython
echo Python launcher "py" was not found. Install Python from python.org and tick Add python.exe to PATH.
pause
exit /b 1

:novenv
echo Could not create the virtual environment.
pause
exit /b 1

:pipfail
echo Package installation failed. Copy the error above and send it to Claude.
pause
exit /b 1
