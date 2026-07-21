@echo off
echo.
echo ==========================================
echo   LinkedinPython Setup (Windows)
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

:: Desktop shortcut -> launch_dashboard.bat
echo.
echo Creating desktop shortcut...
set "SHORTCUT=%USERPROFILE%\Desktop\KarrierMultiSource.lnk"
set "TARGET=%~dp0launch_dashboard.bat"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -COM WScript.Shell).CreateShortcut('%SHORTCUT%'); $s.TargetPath='%TARGET%'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%SystemRoot%\System32\SHELL32.dll,13'; $s.Description='KarrierMultiSource Job Dashboard (LinkedIn, Indeed, karriere.at, Xing)'; $s.Save()"
if exist "%SHORTCUT%" (
    echo [OK] Desktop shortcut created: KarrierMultiSource
) else (
    echo [WARN] Could not create desktop shortcut ^(run launch_dashboard.bat directly^)
)

echo.
echo ==========================================
echo   Setup complete!
echo ==========================================
echo.
echo To start the dashboard, either:
echo   - Double-click the "LinkedinPython" shortcut on your Desktop, or
echo   - Double-click launch_dashboard.bat in this folder, or
echo   - Run manually:  venv\Scripts\activate  ^&  python app.py
echo.
echo The dashboard opens at http://localhost:5000
echo.
pause
