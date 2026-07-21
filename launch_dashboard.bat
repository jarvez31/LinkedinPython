@echo off
:: ===========================================================================
::  LinkedinPython — one-click launcher
::  Activates the right Python environment, opens the dashboard in your
::  browser, and starts the server. Prefers the conda env 'scraper'
::  (developer setup); falls back to venv (end-user setup from setup.bat).
:: ===========================================================================
cd /d "%~dp0"
set "ACTIVATED="

:: ---- 1. conda env 'scraper' under %USERPROFILE%\anaconda3 ----
if not defined ACTIVATED if exist "%USERPROFILE%\anaconda3\Scripts\activate.bat" if exist "%USERPROFILE%\anaconda3\envs\scraper\python.exe" (
    call "%USERPROFILE%\anaconda3\Scripts\activate.bat" scraper
    set "ACTIVATED=1"
)

:: ---- 2. conda env 'scraper' under %USERPROFILE%\miniconda3 ----
if not defined ACTIVATED if exist "%USERPROFILE%\miniconda3\Scripts\activate.bat" if exist "%USERPROFILE%\miniconda3\envs\scraper\python.exe" (
    call "%USERPROFILE%\miniconda3\Scripts\activate.bat" scraper
    set "ACTIVATED=1"
)

:: ---- 3. conda on PATH ----
if not defined ACTIVATED (
    where conda >nul 2>&1 && call conda activate scraper && set "ACTIVATED=1"
)

:: ---- 4. fall back to venv (end-user setup) ----
if not defined ACTIVATED if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    set "ACTIVATED=1"
)

if not defined ACTIVATED (
    echo [ERROR] Could not find conda env 'scraper' or a venv in this folder.
    echo Run setup.bat, or create the env and install requirements.txt.
    pause
    exit /b 1
)

:: ---- Self-heal: only installs if a required package is actually missing ----
:: Keeps normal launches instant; auto-fixes things like "No module named 'openai'".
python -c "import flask, openai, anthropic, playwright, dotenv" >nul 2>&1
if errorlevel 1 (
    echo.
    echo Missing dependencies detected — installing once ^(this may take a minute^)...
    python -m pip install -r requirements.txt
    python -m playwright install chromium
    echo Dependencies ready.
)

:: Open the dashboard ~4s after launch, once the server is accepting requests.
start "" /min cmd /c "timeout /t 4 >nul & start "" http://localhost:5000"

echo.
echo Starting KarrierMultiSource dashboard at http://localhost:5000
echo Close this window (or press Ctrl+C) to stop the server.
echo.
python app.py

pause
