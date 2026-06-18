@echo off
setlocal
chcp 65001 >nul

set "PROJECT_ROOT=%~dp0"
set "CONDA_ENV_PREFIX=%PROJECT_ROOT%env"
set "CONDA_PYTHON=%CONDA_ENV_PREFIX%\python.exe"
set "PROJECT_CONDARC=%PROJECT_ROOT%.condarc"
set "CONDA_PKGS_DIRS=%PROJECT_ROOT%.conda_pkgs"
set "PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple"
set "TORCH_WHL_INDEX_URL=https://download.pytorch.org/whl/cu126"
if not defined HF_ENDPOINT set "HF_ENDPOINT=https://hf-mirror.com"
cd /d "%PROJECT_ROOT%"
mkdir "%PROJECT_ROOT%.tmp" 2>nul
mkdir "%CONDA_PKGS_DIRS%" 2>nul
set "CONDARC=%PROJECT_CONDARC%"

if not exist "%PROJECT_CONDARC%" (
    echo [ERROR] Project Conda mirror config was not found: %PROJECT_CONDARC%
    echo [HINT] Restore .condarc in the repository root, then rerun bootstrap_windows.bat.
    pause
    exit /b 1
)

where conda >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Conda was not found on PATH.
    echo [HINT] Please install Miniconda or Anaconda, then rerun bootstrap_windows.bat.
    pause
    exit /b 1
)

echo [BOOTSTRAP] Ensuring conda environment %CONDA_ENV_PREFIX% ...
echo [BOOTSTRAP] Using project Conda mirror config: %PROJECT_CONDARC%
echo [BOOTSTRAP] Using project package cache: %CONDA_PKGS_DIRS%
echo [BOOTSTRAP] Using Hugging Face endpoint: %HF_ENDPOINT%
if exist "%CONDA_ENV_PREFIX%" if not exist "%CONDA_PYTHON%" (
    echo [BOOTSTRAP] Existing env directory is incomplete. Rebuilding %CONDA_ENV_PREFIX% ...
    rmdir /s /q "%CONDA_ENV_PREFIX%"
)

if exist "%CONDA_PYTHON%" (
    echo [BOOTSTRAP] Checking existing conda env health...
    "%CONDA_PYTHON%" -m app.cli runtime-health --profile core --quiet
    if errorlevel 1 (
        echo [BOOTSTRAP] Existing env failed runtime health checks.
        echo [BOOTSTRAP] Rebuilding fixed prefix env at %CONDA_ENV_PREFIX% ...
        rmdir /s /q "%CONDA_ENV_PREFIX%"
        if exist "%CONDA_ENV_PREFIX%" (
            echo [ERROR] Failed to remove unhealthy conda environment: %CONDA_ENV_PREFIX%
            pause
            exit /b 1
        )
    )
)

if not exist "%CONDA_PYTHON%" (
    echo [BOOTSTRAP] Creating conda environment from environment.yml at prefix %CONDA_ENV_PREFIX% ...
    call conda env create -p "%CONDA_ENV_PREFIX%" -f "%PROJECT_ROOT%environment.yml"
    if errorlevel 1 (
        echo [ERROR] Failed to create conda environment.
        echo [HINT] Check whether %PROJECT_CONDARC% is valid and whether the Tsinghua mirror is reachable.
        pause
        exit /b 1
    )
) else (
    echo [BOOTSTRAP] Updating existing conda environment at prefix %CONDA_ENV_PREFIX% ...
    call conda env update -p "%CONDA_ENV_PREFIX%" -f "%PROJECT_ROOT%environment.yml" --prune
    if errorlevel 1 (
        echo [ERROR] Failed to update conda environment.
        echo [HINT] Check whether %PROJECT_CONDARC% is valid and whether the Tsinghua mirror is reachable.
        pause
        exit /b 1
    )
)

echo [BOOTSTRAP] Running project bootstrap inside conda env ...
call conda run -p "%CONDA_ENV_PREFIX%" python -m app.cli bootstrap
if errorlevel 1 (
    echo [ERROR] Project bootstrap failed inside conda environment.
    pause
    exit /b 1
)

echo [SUCCESS] Bootstrap finished.
echo [NEXT] 1. Fill .env
echo [NEXT] 2. Run build_behavior_data.bat
echo [NEXT] 3. Run build_knowledge_base.bat
echo [NEXT] 4. Run conda run -p "%CONDA_ENV_PREFIX%" python -m app.cli build-frontend
echo [NEXT] 5. Run start_windows.bat
pause
