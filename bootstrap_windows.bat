@echo off
setlocal
chcp 65001 >nul

set "PROJECT_ROOT=%~dp0"
set "VENV_DIR=%PROJECT_ROOT%.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "BOOTSTRAP_PYTHON="
cd /d "%PROJECT_ROOT%"

echo [BOOTSTRAP] Preparing collaborator runtime...

where py >nul 2>nul
if %errorlevel%==0 (
    py -3.10 -c "import sys; print(sys.version)" >nul 2>nul
    if %errorlevel%==0 (
        set "BOOTSTRAP_PYTHON=py -3.10"
    ) else (
        set "BOOTSTRAP_PYTHON=py"
    )
)

if "%BOOTSTRAP_PYTHON%"=="" (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "BOOTSTRAP_PYTHON=python"
    ) else (
        echo [ERROR] Python was not found on this machine.
        echo [HINT] Please install Python 3.10+ and rerun bootstrap_windows.bat.
        pause
        exit /b 1
    )
)

if not exist "%VENV_PYTHON%" (
    echo [BOOTSTRAP] Creating .venv ...
    %BOOTSTRAP_PYTHON% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create .venv.
        pause
        exit /b 1
    )
)

if not exist "%PROJECT_ROOT%.env" (
    if exist "%PROJECT_ROOT%.env.example" (
        copy "%PROJECT_ROOT%.env.example" "%PROJECT_ROOT%.env" >nul
        echo [BOOTSTRAP] Created .env from .env.example.
    ) else (
        echo [ERROR] .env.example was not found.
        pause
        exit /b 1
    )
)

echo [BOOTSTRAP] Installing Python dependencies...
"%VENV_PYTHON%" -m pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/
if errorlevel 1 (
    echo [ERROR] Failed to upgrade pip.
    pause
    exit /b 1
)

"%VENV_PYTHON%" -m pip install -r "%PROJECT_ROOT%requirements.txt" -i https://mirrors.aliyun.com/pypi/simple/
if errorlevel 1 (
    echo [ERROR] Failed to install requirements.txt.
    pause
    exit /b 1
)

if exist "%PROJECT_ROOT%SoulX-FlashHead\requirements.txt" (
    mkdir "%PROJECT_ROOT%.tmp" 2>nul
    set "SOULX_REQ_WIN=%PROJECT_ROOT%.tmp\soulx_requirements_win.txt"
    findstr /v /i /c:"nvidia-nccl" /c:"xformers" /c:"xfuser" /c:"triton" /c:"flash_attn" "%PROJECT_ROOT%SoulX-FlashHead\requirements.txt" > "%SOULX_REQ_WIN%"
    "%VENV_PYTHON%" -m pip install -r "%SOULX_REQ_WIN%" -i https://mirrors.aliyun.com/pypi/simple/
    if errorlevel 1 (
        echo [ERROR] Failed to install SoulX-FlashHead runtime dependencies.
        pause
        exit /b 1
    )
)

echo [BOOTSTRAP] Downloading required models...
"%VENV_PYTHON%" "%PROJECT_ROOT%scripts\download_models.py"
if errorlevel 1 (
    echo [ERROR] Model download failed.
    echo [HINT] Check the JSON report above and retry after fixing network or Hugging Face access.
    pause
    exit /b 1
)

mkdir "%PROJECT_ROOT%data\processed" 2>nul
mkdir "%PROJECT_ROOT%models" 2>nul

echo.
echo [SUCCESS] Bootstrap finished.
echo [NEXT] 1. Fill .env with your real LLM API key
echo [NEXT] 2. Run build_behavior_data.bat
echo [NEXT] 3. Run build_knowledge_base.bat
echo [NEXT] 4. Run start_windows.bat
pause
