@echo off
setlocal
chcp 65001 >nul

set "PROJECT_ROOT=%~dp0"
set "ENV_DIR=%PROJECT_ROOT%env"
set "PYTHON_EXE=%ENV_DIR%\python.exe"
cd /d "%PROJECT_ROOT%"

echo [START] Running runtime preflight checks...

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python runtime not found. Run setup_windows.bat first.
    pause
    exit /b 1
)

set "PYTHONPATH=%PROJECT_ROOT%;%PROJECT_ROOT%SoulX-FlashHead;%PYTHONPATH%"

"%PYTHON_EXE%" "%PROJECT_ROOT%scripts\preflight_check.py"
if errorlevel 1 (
    echo.
    echo [ERROR] Preflight failed.
    echo [HINT] Check the JSON report above, then fix .env / ffmpeg / data build steps first.
    echo [HINT] Typical recovery order:
    echo        1. setup_windows.bat
    echo        2. build_behavior_data.bat
    echo        3. build_knowledge_base.bat
    pause
    exit /b 1
)

echo [START] Launching backend at http://localhost:8000 ...
start "FastAPI-Backend" cmd /c "title FastAPI-Backend && cd /d "%PROJECT_ROOT%" && "%PYTHON_EXE%" -m uvicorn app.main:app --host 0.0.0.0 --port 8000"

timeout /t 5 /nobreak >nul
start http://localhost:8000/

echo [SUCCESS] Frontend: http://localhost:8000/
echo [SUCCESS] Admin:    http://localhost:8000/admin
echo [INFO] Default admin account: admin / admin123
pause
