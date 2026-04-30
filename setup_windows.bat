@echo off
setlocal
chcp 65001 >nul

set "PROJECT_ROOT=%~dp0"
set "ENV_PATH=%PROJECT_ROOT%env"
cd /d "%PROJECT_ROOT%"

echo [SETUP] Preparing Python environment only...

if not exist "%ENV_PATH%\python.exe" (
    echo [ERROR] Embedded Python environment not found at "%ENV_PATH%".
    pause
    exit /b 1
)

if not exist "%PROJECT_ROOT%.env" (
    if exist "%PROJECT_ROOT%.env.example" (
        copy "%PROJECT_ROOT%.env.example" "%PROJECT_ROOT%.env" >nul
        echo [INFO] Created .env from .env.example. Please fill your real API values.
    ) else (
        echo [ERROR] .env.example was not found.
        pause
        exit /b 1
    )
)

echo [SETUP] Installing Python dependencies...
"%ENV_PATH%\python.exe" -m pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/
if errorlevel 1 (
    echo [ERROR] Failed to upgrade pip.
    pause
    exit /b 1
)

"%ENV_PATH%\python.exe" -m pip install -r "%PROJECT_ROOT%requirements.txt" -i https://mirrors.aliyun.com/pypi/simple/
if errorlevel 1 (
    echo [ERROR] Failed to install requirements.txt.
    pause
    exit /b 1
)

if exist "%PROJECT_ROOT%SoulX-FlashHead\requirements.txt" (
    mkdir "%PROJECT_ROOT%.tmp" 2>nul
    set "SOULX_REQ_WIN=%PROJECT_ROOT%.tmp\soulx_requirements_win.txt"
    findstr /v /i /c:"nvidia-nccl" /c:"xformers" /c:"xfuser" /c:"triton" /c:"flash_attn" "%PROJECT_ROOT%SoulX-FlashHead\requirements.txt" > "%SOULX_REQ_WIN%"
    "%ENV_PATH%\python.exe" -m pip install -r "%SOULX_REQ_WIN%" -i https://mirrors.aliyun.com/pypi/simple/
    if errorlevel 1 (
        echo [ERROR] Failed to install SoulX-FlashHead runtime dependencies.
        pause
        exit /b 1
    )
)

mkdir "%PROJECT_ROOT%data\processed" 2>nul
mkdir "%PROJECT_ROOT%models" 2>nul

echo.
echo [SUCCESS] Environment preparation finished.
echo [NEXT] 1. Fill .env
echo [NEXT] 2. Run build_behavior_data.bat
echo [NEXT] 3. Run build_knowledge_base.bat
echo [NEXT] 4. Run start_windows.bat
pause
