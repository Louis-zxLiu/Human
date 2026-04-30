@echo off
setlocal
chcp 65001 >nul

set "PROJECT_ROOT=%~dp0"
set "PYTHON_EXE=%PROJECT_ROOT%.venv\Scripts\python.exe"
cd /d "%PROJECT_ROOT%"

echo [START] Running runtime preflight checks...

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python runtime not found in .venv.
    echo [HINT] Run bootstrap_windows.bat first.
    pause
    exit /b 1
)

set "PYTHONPATH=%PROJECT_ROOT%;%PROJECT_ROOT%SoulX-FlashHead;%PYTHONPATH%"

"%PYTHON_EXE%" "%PROJECT_ROOT%scripts\preflight_check.py"
if errorlevel 1 (
    echo.
    echo [ERROR] Preflight failed.
    echo [HINT] Check the JSON report above and follow the suggested next steps.
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
