@echo off
:: ===========================================================================
::  KarrierMultiSource — REMOTE launcher (phone access via Tailscale/LAN)
::  Same as launch_dashboard.bat, but binds the server to all network
::  interfaces (HOST=0.0.0.0) so your phone can reach it over Tailscale
::  (mobile data, anywhere) or the local network.
::
::  SECURITY: the dashboard has no password and /config returns your saved
::  credentials. Only run this behind Tailscale (private) or on a trusted
::  LAN. Do NOT put it on a public tunnel without a password gate first.
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
python -c "import flask, openai, anthropic, playwright, dotenv" >nul 2>&1
if errorlevel 1 (
    echo.
    echo Missing dependencies detected — installing once ^(this may take a minute^)...
    python -m pip install -r requirements.txt
    python -m playwright install chromium
    echo Dependencies ready.
)

:: Bind to all interfaces so Tailscale / LAN clients (your phone) can connect.
set "HOST=0.0.0.0"

echo.
echo ============================================================
echo   KarrierMultiSource — REMOTE mode (phone access enabled)
echo ============================================================
echo   On THIS PC:        http://localhost:5000
for /f "tokens=*" %%i in ('tailscale ip -4 2^>nul') do echo   On your PHONE:     http://%%i:5000   ^(Tailscale, mobile data^)
echo.
echo   If no PHONE line appeared, Tailscale isn't up yet — run:
echo       tailscale up
echo   then find the address with:  tailscale ip -4
echo.
echo   Keep this window open. Ctrl+C to stop the server.
echo ============================================================
echo.

python app.py

pause
