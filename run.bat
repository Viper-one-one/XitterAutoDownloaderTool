@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" main.py %*
    exit /b 0
)

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py %*
    exit /b %ERRORLEVEL%
)

where pythonw >nul 2>nul
if %ERRORLEVEL%==0 (
    start "" pythonw main.py %*
    exit /b 0
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
    echo [WARN] .venv not found, launching with system python...
    python main.py %*
    exit /b %ERRORLEVEL%
)

echo [ERROR] Python virtual environment (.venv) not found and system python is unavailable.
echo Create .venv and run: .venv\Scripts\python.exe -m pip install -r requirements.txt
pause
exit /b 1
