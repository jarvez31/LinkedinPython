@echo off
echo.
echo ==========================================
echo   KarrierPython Setup (Windows)
echo   Job Intelligence Dashboard
echo ==========================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install from https://python.org and re-run.
    pause
    exit /b 1
)
echo [OK] Python found

:: Create virtual environment
if not exist "venv" (
    python -m venv venv
    echo [OK] Virtual environment created
) else (
    echo [OK] Virtual environment already exists
)

:: Activate
call venv\Scripts\activate.bat

:: Install dependencies
echo.
echo Installing dependencies...
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo [OK] Dependencies installed

:: Install Playwright + Chromium
echo.
echo Installing Playwright + Chromium browser...
echo (This may take 1-2 minutes on first run)
playwright install chromium
echo [OK] Chromium installed

:: Create folders
if not exist "data" mkdir data
if not exist "outputs" mkdir outputs
if not exist "attachments" mkdir attachments
echo [OK] Folders created

:: .env setup
if not exist ".env" (
    copy .env.example .env >nul
    echo [OK] .env created from .env.example
) else (
    echo [OK] .env already exists
)

echo.
echo ==========================================
echo   Setup complete!
echo ==========================================
echo.
echo To start the dashboard:
echo.
echo   venv\Scripts\activate
echo   python app.py
echo.
echo Then open http://localhost:5000 in your browser.
echo.
pause
