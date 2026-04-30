@echo off
setlocal
chcp 65001 >nul

set "PROJECT_ROOT=%~dp0"
set "PYTHON_EXE=%PROJECT_ROOT%.venv\Scripts\python.exe"
cd /d "%PROJECT_ROOT%"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python runtime not found in .venv.
    echo [HINT] Run bootstrap_windows.bat first.
    pause
    exit /b 1
)

echo [BUILD] Building scenic knowledge base from local Lingshan documents...
"%PYTHON_EXE%" -m app.rag.init_db
if errorlevel 1 (
    echo [ERROR] Knowledge base build failed.
    pause
    exit /b 1
)

echo [SUCCESS] Scenic knowledge base is ready.
pause
