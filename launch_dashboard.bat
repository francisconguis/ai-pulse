@echo off
title AI Pulse Dashboard
cd /d "%~dp0"

set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
)

echo Checking dependencies...
"%PYTHON_EXE%" -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo Installing required packages ^(first time only^)...
    "%PYTHON_EXE%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Failed to install dependencies. Make sure Python 3.10+ is installed.
        pause
        exit /b 1
    )
)

echo Launching AI Pulse Dashboard...
"%PYTHON_EXE%" -m streamlit run dashboard/app.py
if errorlevel 1 (
    echo.
    echo Dashboard exited with an error.
    pause
)
