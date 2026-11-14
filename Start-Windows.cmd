@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))"
if errorlevel 1 goto python_required
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 goto failed
)
fc /b requirements.txt .venv\brickprint-requirements.txt >nul 2>nul
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto failed
    copy /y requirements.txt .venv\brickprint-requirements.txt >nul
)
".venv\Scripts\python.exe" -m brickprint %*
if errorlevel 1 goto failed
exit /b 0
:python_required
echo Install Python 3.11 or newer from https://www.python.org/downloads/windows/ and rerun this file.
:failed
pause
exit /b 1
