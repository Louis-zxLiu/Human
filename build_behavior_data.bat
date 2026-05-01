@echo off
setlocal
chcp 65001 >nul

set "PROJECT_ROOT=%~dp0"
set "CONDA_ENV_PREFIX=%PROJECT_ROOT%env"
set "CONDA_PYTHON=%CONDA_ENV_PREFIX%\python.exe"
set "CONDARC=%PROJECT_ROOT%.condarc"
set "CONDA_PKGS_DIRS=%PROJECT_ROOT%.conda_pkgs"
cd /d "%PROJECT_ROOT%"

if not exist "%CONDA_PYTHON%" (
    echo [ERROR] Conda environment is missing: %CONDA_ENV_PREFIX%
    echo [HINT] Run bootstrap_windows.bat first.
    pause
    exit /b 1
)

"%CONDA_PYTHON%" -m app.cli runtime-health --quiet
if errorlevel 1 (
    echo [ERROR] Current env is not healthy enough to run prepare-data.
    echo [HINT] Remove D:\Human\env and rerun bootstrap_windows.bat.
    pause
    exit /b 1
)

call conda run -p "%CONDA_ENV_PREFIX%" python -m app.cli prepare-data
pause
