@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "PROJECT_ROOT=%~dp0"
set "CONDA_ENV_PREFIX=%PROJECT_ROOT%env"
set "CONDA_PYTHON=%CONDA_ENV_PREFIX%\python.exe"
set "CONDARC=%PROJECT_ROOT%.condarc"
set "CONDA_PKGS_DIRS=%PROJECT_ROOT%.conda_pkgs"
set "HOST=127.0.0.1"
set "PORT=8000"

cd /d "%PROJECT_ROOT%"

if not exist "%CONDA_PYTHON%" (
    echo [ERROR] Conda environment is missing: %CONDA_ENV_PREFIX%
    echo [HINT] Run bootstrap_windows.bat first.
    pause
    exit /b 1
)

"%CONDA_PYTHON%" -m app.cli runtime-health --quiet
if errorlevel 1 (
    echo [ERROR] Current env is not healthy enough to start the system.
    echo [HINT] Remove D:\Human\env and rerun bootstrap_windows.bat.
    pause
    exit /b 1
)

start "Human Backend" cmd /k "chcp 65001 >nul && cd /d ""%PROJECT_ROOT%"" && set ""CONDARC=%CONDARC%"" && set ""CONDA_PKGS_DIRS=%CONDA_PKGS_DIRS%"" && call conda run -p ""%CONDA_ENV_PREFIX%"" python -m app.cli start --host %HOST% --port %PORT%"

set "READY="
for /l %%I in (1,1,20) do (
    powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing http://%HOST%:%PORT%/health -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>nul
    if not errorlevel 1 (
        set "READY=1"
        goto :ready
    )
    timeout /t 1 /nobreak >nul
)

:ready
if defined READY (
    echo [SUCCESS] Service started.
    echo [URL] Visitor: http://%HOST%:%PORT%/
    echo [URL] Admin:   http://%HOST%:%PORT%/admin
    echo [URL] Login:   http://%HOST%:%PORT%/login
    start "" "http://%HOST%:%PORT%/"
    exit /b 0
)

echo [INFO] Backend window has been opened, but health check did not pass in time.
echo [INFO] Check the "Human Backend" window and then open:
echo [URL] Visitor: http://%HOST%:%PORT%/
echo [URL] Admin:   http://%HOST%:%PORT%/admin
echo [URL] Login:   http://%HOST%:%PORT%/login
exit /b 1
