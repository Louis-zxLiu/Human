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

echo [BUILD] Importing scenic structured facts into attractions table...
"%PYTHON_EXE%" "%PROJECT_ROOT%scripts\import_docx_to_sql.py"
if errorlevel 1 (
    echo [ERROR] Failed to import scenic fact data.
    pause
    exit /b 1
)

echo [BUILD] Importing visitor behavior analytics data from the competition Excel...
"%PYTHON_EXE%" "%PROJECT_ROOT%scripts\offline_data_processor.py"
if errorlevel 1 (
    echo [ERROR] Failed to import visitor behavior analytics data.
    pause
    exit /b 1
)

echo [SUCCESS] Behavior analytics database is ready.
pause
